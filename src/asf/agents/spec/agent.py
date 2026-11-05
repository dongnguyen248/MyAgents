from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from asf.agents._shared.model_call import call_model
from asf.agents._shared.model_errors import invalid_response
from asf.agents._shared.routing import tier_metadata
from asf.agents.base import AgentRuntime, BaseAgent, Issue
from asf.agents.spec.prompts import SpecPrompts, SpecTemplate, build_spec_messages
from asf.contracts.models import AgentMetadata, AgentRequest, Artifact, ModelRequest

__all__ = ["MAX_REQUIREMENT_CHARS", "SpecAgent"]

# Generous on purpose: users paste whole briefs/test-case documents as
# the requirement. 200k chars matches the task agent's text cap
# (MAX_TASK_TEXT_CHARS); the old 20k cap failed real first runs.
MAX_REQUIREMENT_CHARS: int = 200_000


class SpecAgent(BaseAgent):
    """Agent responsible for creating and revising software specifications."""

    def __init__(
        self,
        runtime: AgentRuntime,
        *,
        prompts: SpecPrompts,
        template: SpecTemplate,
        model: str | None = None,
        parameters: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(runtime)
        self._prompts = prompts
        self._template = template
        self._model = model
        self._parameters = dict(parameters or {})
        self._metadata = AgentMetadata(
            id="agent-spec",
            name="Specification Agent",
            type="spec",
            version="1.0.0",
            status="IDLE",
            capabilities=["write-spec", "revise-spec"],
            configuration={},
        )

    @property
    def metadata(self) -> AgentMetadata:
        return self._metadata

    def _compute_revision_count(self, request: AgentRequest) -> int:
        spec_arts = [a for a in request.artifacts if a.type == "SPEC"]
        if spec_arts:
            try:
                return int(spec_arts[0].version)
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

        # 2. input.requirement
        if "requirement" not in request.input:
            issues.append(Issue("input.requirement", "Missing requirement in input"))
        elif not isinstance(request.input["requirement"], str):
            issues.append(Issue("input.requirement", "input.requirement must be a string"))
        else:
            req_text = request.input["requirement"].strip()
            if not req_text:
                issues.append(Issue("input.requirement", "input.requirement must be non-empty"))
            elif len(request.input["requirement"]) > MAX_REQUIREMENT_CHARS:
                issues.append(
                    Issue(
                        "input.requirement",
                        f"input.requirement exceeds maximum length of "
                        f"{MAX_REQUIREMENT_CHARS} characters",
                    )
                )

        # 3. input.language, if present
        if "language" in request.input:
            lang = request.input["language"]
            if not isinstance(lang, str) or not lang.strip():
                issues.append(Issue("input.language", "input.language must be a non-empty string"))

        # 4. At most one artifact of type SPEC
        spec_arts = [a for a in request.artifacts if a.type == "SPEC"]
        if len(spec_arts) > 1:
            issues.append(
                Issue("artifacts", "At most one artifact of type SPEC is permitted")
            )

        # 5. Revision mode iff a SPEC artifact is present
        if len(spec_arts) == 1:
            spec_art = spec_arts[0]
            art_idx = request.artifacts.index(spec_art)

            if not request.feedback:
                issues.append(
                    Issue("feedback", "Reviewer feedback is required when revising a specification")
                )

            # Content must be a mapping with non-empty str "text"
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

            # Version must match ^[1-9][0-9]*$
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

        # 6. Non-empty feedback without a SPEC artifact
        if request.feedback and not spec_arts:
            issues.append(
                Issue("artifacts", "feedback provided without a previous SPEC artifact to revise")
            )

        # 7. metadata.attempt, if present
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

        return issues

    def _run(self, request: AgentRequest) -> tuple[dict[str, Any], list[Artifact]]:
        spec_arts = [a for a in request.artifacts if a.type == "SPEC"]
        is_revision = len(spec_arts) == 1
        prev_spec_art = spec_arts[0] if is_revision else None
        if (
            prev_spec_art
            and isinstance(prev_spec_art.content, dict)
            and "text" in prev_spec_art.content
        ):
            previous_spec: tuple[str, str] | None = (
                prev_spec_art.version,
                prev_spec_art.content["text"],
            )
        else:
            previous_spec = None

        requirement = request.input["requirement"].strip()
        language = request.input.get("language")
        project_context = request.context.get("project")

        messages = build_spec_messages(
            prompts=self._prompts,
            template=self._template,
            requirement=requirement,
            language=language,
            project_context=project_context,
            previous_spec=previous_spec,
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

        response = call_model(self._runtime.models, model_req)
        reply = response.content.strip()

        # Unwrap single code fence if wrapped
        if reply.startswith("```") and reply.endswith("```"):
            lines = reply.splitlines()
            if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].strip() == "```":
                reply = "\n".join(lines[1:-1]).strip()

        if not reply:
            raise invalid_response(
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
            raise invalid_response(
                f"Model response is missing required template sections: {missing_sections}",
                details={"missingSections": missing_sections},
            )

        if is_revision and prev_spec_art:
            version = str(int(prev_spec_art.version) + 1)
        else:
            version = "1"

        art_metadata: dict[str, Any] = {
            "template": "spec",
            "model": response.model,
            "usage": {
                "promptTokens": response.usage.prompt_tokens,
                "completionTokens": response.usage.completion_tokens,
            },
        }
        if is_revision and prev_spec_art:
            art_metadata["revisionOf"] = prev_spec_art.id
        if language and isinstance(language, str) and language.strip():
            art_metadata["language"] = language

        art_id = self._runtime.new_id()
        placeholder_dt = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        artifact = Artifact(
            id=art_id,
            type="SPEC",
            name="SPEC.md",
            version=version,
            content={"format": "markdown", "text": reply},
            created_by=self.metadata.id,
            created_at=placeholder_dt,
            metadata=art_metadata,
        )

        summary = "Specification revised" if is_revision else "Specification created"
        output = {
            "summary": summary,
            "artifactId": art_id,
            "version": version,
        }

        return output, [artifact]
