from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from asf.agents._shared.routing import tier_metadata
from asf.agents.base import AgentRuntime, BaseAgent, Issue
from asf.agents.plan.prompts import (
    MilestoneValidationError,
    PlanPrompts,
    PlanTemplate,
    build_plan_messages,
    validate_milestones,
)
from asf.contracts.models import AgentMetadata, AgentRequest, Artifact, ModelRequest
from asf.models.errors import ModelGatewayError

__all__ = ["MAX_PLAN_CHARS", "PlanAgent"]

MAX_PLAN_CHARS: int = 50000


class PlanAgent(BaseAgent):
    """Agent responsible for creating and revising implementation plans."""

    def __init__(
        self,
        runtime: AgentRuntime,
        *,
        prompts: PlanPrompts,
        template: PlanTemplate,
        model: str | None = None,
        parameters: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(runtime)
        self._prompts = prompts
        self._template = template
        self._model = model
        self._parameters = dict(parameters or {})
        self._metadata = AgentMetadata(
            id="agent-plan",
            name="Planning Agent",
            type="plan",
            version="1.0.0",
            status="IDLE",
            capabilities=["write-plan", "revise-plan"],
            configuration={},
        )

    @property
    def metadata(self) -> AgentMetadata:
        return self._metadata

    def _compute_revision_count(self, request: AgentRequest) -> int:
        """Computes revision count from the PLAN artifact version."""
        plan_arts = [a for a in request.artifacts if a.type == "PLAN"]
        if plan_arts:
            try:
                return int(plan_arts[0].version)
            except (ValueError, TypeError):
                return 0
        return 0

    def _check(self, request: AgentRequest) -> list[Issue]:
        issues: list[Issue] = []

        # 1. agentId check
        if request.agent_id != self.metadata.id:
            issues.append(
                Issue(
                    "agentId",
                    f"agentId '{request.agent_id}' does not match '{self.metadata.id}'",
                )
            )

        # 2. input.requirement must not be present (SPEC provides the requirement)
        if "requirement" in request.input:
            issues.append(
                Issue(
                    "input.requirement",
                    "input.requirement must not be present for PlanAgent; "
                    "SPEC artifact provides the requirement",
                )
            )

        # 3. input.language, if present
        if "language" in request.input:
            lang = request.input["language"]
            if not isinstance(lang, str) or not lang.strip():
                issues.append(Issue("input.language", "input.language must be a non-empty string"))

        # 4. Exactly one SPEC artifact required
        spec_arts = [a for a in request.artifacts if a.type == "SPEC"]
        if len(spec_arts) != 1:
            issues.append(
                Issue("artifacts", "Exactly one artifact of type SPEC is required")
            )
        else:
            spec_art = spec_arts[0]
            art_idx = request.artifacts.index(spec_art)

            # SPEC content must be a mapping with non-empty str "text"
            if (
                not isinstance(spec_art.content, dict)
                or not isinstance(spec_art.content.get("text"), str)
                or not spec_art.content.get("text", "").strip()
            ):
                issues.append(
                    Issue(
                        f"artifacts[{art_idx}].content.text",
                        "SPEC artifact must have inline content mapping with non-empty 'text'",
                    )
                )

            # SPEC version must match ^[1-9][0-9]*$
            is_valid_ver = isinstance(spec_art.version, str) and bool(
                re.match(r"^[1-9][0-9]*$", spec_art.version)
            )
            if not is_valid_ver:
                issues.append(
                    Issue(
                        f"artifacts[{art_idx}].version",
                        f"SPEC artifact version '{spec_art.version}' must match '^[1-9][0-9]*$'",
                    )
                )

        # 5. At most one PLAN artifact (for revision mode)
        plan_arts = [a for a in request.artifacts if a.type == "PLAN"]
        if len(plan_arts) > 1:
            issues.append(
                Issue("artifacts", "At most one artifact of type PLAN is permitted")
            )

        is_revision = len(plan_arts) == 1

        # 6. Revision mode iff a PLAN artifact is present
        if is_revision:
            plan_art = plan_arts[0]
            art_idx = request.artifacts.index(plan_art)

            if not request.feedback:
                issues.append(
                    Issue("feedback", "Reviewer feedback is required when revising a plan")
                )

            # Content must be a mapping with non-empty str "text"
            if (
                not isinstance(plan_art.content, dict)
                or not isinstance(plan_art.content.get("text"), str)
                or not plan_art.content.get("text", "").strip()
            ):
                issues.append(
                    Issue(
                        f"artifacts[{art_idx}].content.text",
                        "PLAN artifact must have inline content mapping with non-empty 'text'",
                    )
                )

            # Version must match ^[1-9][0-9]*$
            is_valid_ver = isinstance(plan_art.version, str) and bool(
                re.match(r"^[1-9][0-9]*$", plan_art.version)
            )
            if not is_valid_ver:
                issues.append(
                    Issue(
                        f"artifacts[{art_idx}].version",
                        f"PLAN artifact version '{plan_art.version}' must match '^[1-9][0-9]*$'",
                    )
                )

        # 7. Feedback without PLAN artifact
        if request.feedback and not is_revision:
            issues.append(
                Issue("artifacts", "feedback provided without a previous PLAN artifact to revise")
            )

        # 8. Reject unknown artifact types
        allowed_types = {"SPEC", "PLAN"}
        for idx, art in enumerate(request.artifacts):
            if art.type not in allowed_types:
                issues.append(
                    Issue(
                        f"artifacts[{idx}].type",
                        f"Unknown artifact type '{art.type}'; allowed: {sorted(allowed_types)}",
                    )
                )

        # 9. metadata.attempt, if present
        if "attempt" in request.metadata:
            attempt_val = request.metadata["attempt"]
            if (
                not isinstance(attempt_val, int)
                or isinstance(attempt_val, bool)
                or attempt_val < 1
            ):
                issues.append(
                    Issue("metadata.attempt", "metadata.attempt must be an integer >= 1")
                )

        # 10. SPEC + PLAN content size limit
        spec_arts = [a for a in request.artifacts if a.type == "SPEC"]
        plan_arts = [a for a in request.artifacts if a.type == "PLAN"]
        total_chars = 0
        for art in spec_arts + plan_arts:
            if isinstance(art.content, dict) and isinstance(art.content.get("text"), str):
                total_chars += len(art.content["text"])
        if total_chars > MAX_PLAN_CHARS:
            issues.append(
                Issue(
                    "artifacts",
                    f"Combined SPEC+PLAN content exceeds {MAX_PLAN_CHARS} characters",
                )
            )

        return issues

    def _run(self, request: AgentRequest) -> tuple[dict[str, Any], list[Artifact]]:
        # Extract SPEC artifact (always required)
        spec_arts = [a for a in request.artifacts if a.type == "SPEC"]
        spec_art = spec_arts[0]
        spec_artifact_dict = spec_art.to_contract()

        # Check for revision mode
        plan_arts = [a for a in request.artifacts if a.type == "PLAN"]
        is_revision = len(plan_arts) == 1
        prev_plan_art = plan_arts[0] if is_revision else None

        previous_plan: tuple[str, str] | None = None
        if (
            prev_plan_art
            and isinstance(prev_plan_art.content, dict)
            and "text" in prev_plan_art.content
        ):
            previous_plan = (
                prev_plan_art.version,
                prev_plan_art.content["text"],
            )

        language = request.input.get("language")
        project_context = request.context.get("project")

        messages = build_plan_messages(
            prompts=self._prompts,
            template=self._template,
            spec_artifact=spec_artifact_dict,
            language=language,
            project_context=project_context,
            previous_plan=previous_plan,
            feedback=request.feedback,
        )

        model_req = ModelRequest(
            messages=messages,
            parameters=dict(self._parameters),
            model=self._model,
            metadata={
                "agentId": self.metadata.id, "requestId": request.request_id,
                **tier_metadata(request.context),
            },
        )

        response = self._runtime.models.complete(model_req)
        reply = response.content.strip()

        # Unwrap single code fence if wrapped
        if reply.startswith("```") and reply.endswith("```"):
            lines = reply.splitlines()
            if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].strip() == "```":
                reply = "\n".join(lines[1:-1]).strip()

        if not reply:
            raise ModelGatewayError(
                "LLM_INVALID_RESPONSE",
                "Model returned an empty response",
            )

        # Validate required template sections
        reply_heading_lines = {
            line.strip()
            for line in reply.splitlines()
            if line.strip().startswith("## ")
        }
        missing_sections = [
            sec for sec in self._template.required_sections
            if sec not in reply_heading_lines
        ]
        if missing_sections:
            raise ModelGatewayError(
                "LLM_INVALID_RESPONSE",
                f"Model response is missing required template sections: {missing_sections}",
                details={"missingSections": missing_sections},
            )

        # Validate milestone structure
        try:
            validate_milestones(reply)
        except MilestoneValidationError as e:
            raise ModelGatewayError(
                "LLM_INVALID_RESPONSE",
                "Model response has invalid milestone structure",
                details={"milestoneIssues": e.issues},
            )

        # Validate "Linked SPEC" section matches the input SPEC artifact
        linked_spec_issues = self._validate_linked_spec_section(reply, spec_art)
        if linked_spec_issues:
            raise ModelGatewayError(
                "LLM_INVALID_RESPONSE",
                "Model response has invalid Linked SPEC section",
                details={"linkedSpecIssues": linked_spec_issues},
            )

        # Determine version
        if is_revision and prev_plan_art:
            version = str(int(prev_plan_art.version) + 1)
        else:
            version = "1"

        # Build artifact metadata with traceability
        art_metadata: dict[str, Any] = {
            "template": "plan",
            "model": response.model,
            "usage": {
                "promptTokens": response.usage.prompt_tokens,
                "completionTokens": response.usage.completion_tokens,
            },
            "specArtifactId": spec_art.id,
            "specVersion": spec_art.version,
        }
        if is_revision and prev_plan_art:
            art_metadata["revisionOf"] = prev_plan_art.id
        if language and isinstance(language, str) and language.strip():
            art_metadata["language"] = language

        art_id = self._runtime.new_id()
        placeholder_dt = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        artifact = Artifact(
            id=art_id,
            type="PLAN",
            name="PLAN.md",
            version=version,
            content={"format": "markdown", "text": reply},
            created_by=self.metadata.id,
            created_at=placeholder_dt,
            metadata=art_metadata,
        )

        summary = "Plan revised" if is_revision else "Plan created"
        output = {
            "summary": summary,
            "artifactId": art_id,
            "version": version,
        }

        return output, [artifact]

    @staticmethod
    def _validate_linked_spec_section(reply: str, spec_art: Artifact) -> list[str]:
        """Validate that the 'Linked SPEC' section in the LLM output matches
        the input SPEC artifact.

        Returns a list of issue strings (empty if valid).
        """
        issues: list[str] = []

        # Find the Linked SPEC section
        lines = reply.splitlines()
        in_linked_spec = False
        found_id = None
        found_version = None

        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped == "## Linked SPEC":
                in_linked_spec = True
                continue
            if in_linked_spec:
                if stripped.startswith("## "):
                    # Next section started
                    break
                if stripped.startswith("ID:"):
                    found_id = stripped[3:].strip()
                elif stripped.startswith("Version:"):
                    found_version = stripped[8:].strip()

        if not in_linked_spec:
            issues.append("Missing '## Linked SPEC' section")
        else:
            if found_id is None:
                issues.append("Linked SPEC section missing 'ID:' line")
            elif found_id != spec_art.id:
                issues.append(
                    f"Linked SPEC ID '{found_id}' does not match input "
                    f"SPEC artifact ID '{spec_art.id}'"
                )

            if found_version is None:
                issues.append("Linked SPEC section missing 'Version:' line")
            elif found_version != spec_art.version:
                issues.append(
                    f"Linked SPEC version '{found_version}' does not match "
                    f"input SPEC artifact version '{spec_art.version}'"
                )

        return issues