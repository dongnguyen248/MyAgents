from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from asf.agents._shared.model_call import call_model
from asf.agents._shared.model_errors import invalid_response
from asf.agents._shared.reply_text import heading_lines, unwrap_code_fence
from asf.agents._shared.request_checks import (
    artifacts_of,
    check_agent_id,
    check_artifact_types,
    check_attempt,
    check_language,
    check_orphan_feedback,
    check_required_artifact,
    check_revision_artifact,
)
from asf.agents._shared.routing import tier_metadata
from asf.agents.base import AgentRuntime, BaseAgent, Issue
from asf.agents.plan.prompts import (
    MilestoneValidationError,
    PlanPromptContext,
    PlanPrompts,
    PlanTemplate,
    build_plan_messages,
    validate_milestones,
)
from asf.contracts.models import (
    AgentMetadata,
    AgentRequest,
    Artifact,
    ModelMessage,
    ModelRequest,
    ModelResponse,
)

__all__ = ["MAX_PLAN_CHARS", "PlanAgent", "PlanSettings"]

MAX_PLAN_CHARS: int = 50000

_ALLOWED_TYPES = {"SPEC", "PLAN"}


@dataclass(frozen=True)
class PlanSettings:
    prompts: PlanPrompts
    template: PlanTemplate
    model: str | None = None
    parameters: Mapping[str, Any] | None = None


def _check_requirement_absent(request: AgentRequest) -> list[Issue]:
    if "requirement" not in request.input:
        return []
    message = (
        "input.requirement must not be present for PlanAgent; "
        "SPEC artifact provides the requirement"
    )
    return [Issue("input.requirement", message)]


def _check_content_size(request: AgentRequest) -> list[Issue]:
    total = 0
    for artifact in request.artifacts:
        if artifact.type not in _ALLOWED_TYPES:
            continue
        if isinstance(artifact.content, dict) and isinstance(
            artifact.content.get("text"), str
        ):
            total += len(artifact.content["text"])
    if total > MAX_PLAN_CHARS:
        message = f"Combined SPEC+PLAN content exceeds {MAX_PLAN_CHARS} characters"
        return [Issue("artifacts", message)]
    return []


def _previous_plan(request: AgentRequest) -> Artifact | None:
    plan_arts = artifacts_of(request, "PLAN")
    return plan_arts[0] if len(plan_arts) == 1 else None


def _previous_plan_text(previous: Artifact | None) -> tuple[str, str] | None:
    if previous is None or not isinstance(previous.content, dict):
        return None
    if "text" not in previous.content:
        return None
    return (previous.version, previous.content["text"])


def _linked_spec_values(reply: str) -> tuple[bool, str | None, str | None]:
    found_section = False
    found_id: str | None = None
    found_version: str | None = None
    for line in reply.splitlines():
        stripped = line.strip()
        if stripped == "## Linked SPEC":
            found_section = True
            continue
        if not found_section:
            continue
        if stripped.startswith("## "):
            break
        if stripped.startswith("ID:"):
            found_id = stripped[3:].strip()
        elif stripped.startswith("Version:"):
            found_version = stripped[8:].strip()
    return found_section, found_id, found_version


def _linked_spec_issues(reply: str, spec_art: Artifact) -> list[str]:
    found_section, found_id, found_version = _linked_spec_values(reply)
    if not found_section:
        return ["Missing '## Linked SPEC' section"]
    issues: list[str] = []
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


class PlanAgent(BaseAgent):
    """Agent responsible for creating and revising implementation plans."""

    def __init__(self, runtime: AgentRuntime, settings: PlanSettings) -> None:
        super().__init__(runtime)
        self._prompts = settings.prompts
        self._template = settings.template
        self._model = settings.model
        self._parameters = dict(settings.parameters or {})
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
        plan_arts = artifacts_of(request, "PLAN")
        if plan_arts:
            try:
                return int(plan_arts[0].version)
            except (ValueError, TypeError):
                return 0
        return 0

    def _check(self, request: AgentRequest) -> list[Issue]:
        agent_id_message = (
            f"agentId '{request.agent_id}' does not match '{self.metadata.id}'"
        )
        revision_message = "Reviewer feedback is required when revising a plan"
        validators = [
            lambda: check_agent_id(request, self.metadata.id, agent_id_message),
            lambda: _check_requirement_absent(request),
            lambda: check_language(request, "input.language must be a non-empty string"),
            lambda: check_required_artifact(request, "SPEC"),
            lambda: check_revision_artifact(request, "PLAN", revision_message),
            lambda: check_orphan_feedback(request, "PLAN"),
            lambda: check_artifact_types(request, _ALLOWED_TYPES),
            lambda: check_attempt(request),
            lambda: _check_content_size(request),
        ]
        return [issue for validate in validators for issue in validate()]

    def _run(self, request: AgentRequest) -> tuple[dict[str, Any], list[Artifact]]:
        spec_art = artifacts_of(request, "SPEC")[0]
        previous = _previous_plan(request)
        messages = self._build_messages(request, spec_art, previous)
        response = call_model(
            self._runtime.models, self._model_request(request, messages)
        )
        reply = self._checked_reply(response, spec_art)
        metadata = self._artifact_metadata(request, spec_art, previous, response)
        return self._assemble(previous, reply, metadata)

    def _build_messages(
        self,
        request: AgentRequest,
        spec_art: Artifact,
        previous: Artifact | None,
    ) -> list[ModelMessage]:
        context = PlanPromptContext(
            prompts=self._prompts,
            template=self._template,
            spec_artifact=spec_art.to_contract(),
            language=request.input.get("language"),
            project_context=request.context.get("project"),
            previous_plan=_previous_plan_text(previous),
            feedback=request.feedback,
        )
        return build_plan_messages(context)

    def _model_request(
        self, request: AgentRequest, messages: list[ModelMessage]
    ) -> ModelRequest:
        return ModelRequest(
            messages=messages,
            parameters=dict(self._parameters),
            model=self._model,
            metadata={
                "agentId": self.metadata.id,
                "requestId": request.request_id,
                "cachePrefixMessages": 1,
                **tier_metadata(request.context),
            },
        )

    def _checked_reply(self, response: ModelResponse, spec_art: Artifact) -> str:
        reply = unwrap_code_fence(response.content.strip())
        if not reply:
            raise invalid_response("Model returned an empty response")
        self._require_sections(reply)
        self._require_milestones(reply)
        self._require_linked_spec(reply, spec_art)
        return reply

    def _require_sections(self, reply: str) -> None:
        headings = heading_lines(reply)
        missing = [s for s in self._template.required_sections if s not in headings]
        if missing:
            raise invalid_response(
                f"Model response is missing required template sections: {missing}",
                details={"missingSections": missing},
            )

    def _require_milestones(self, reply: str) -> None:
        try:
            validate_milestones(reply)
        except MilestoneValidationError as error:
            raise invalid_response(
                "Model response has invalid milestone structure",
                details={"milestoneIssues": error.issues},
            ) from None

    def _require_linked_spec(self, reply: str, spec_art: Artifact) -> None:
        issues = _linked_spec_issues(reply, spec_art)
        if issues:
            raise invalid_response(
                "Model response has invalid Linked SPEC section",
                details={"linkedSpecIssues": issues},
            )

    def _assemble(
        self,
        previous: Artifact | None,
        reply: str,
        metadata: dict[str, Any],
    ) -> tuple[dict[str, Any], list[Artifact]]:
        version = str(int(previous.version) + 1) if previous is not None else "1"
        artifact = Artifact(
            id=self._runtime.new_id(),
            type="PLAN",
            name="PLAN.md",
            version=version,
            content={"format": "markdown", "text": reply},
            created_by=self.metadata.id,
            created_at=datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
            metadata=metadata,
        )
        summary = "Plan revised" if previous is not None else "Plan created"
        output = {"summary": summary, "artifactId": artifact.id, "version": version}
        return output, [artifact]

    def _artifact_metadata(
        self,
        request: AgentRequest,
        spec_art: Artifact,
        previous: Artifact | None,
        response: ModelResponse,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "template": "plan",
            "model": response.model,
            "usage": {
                "promptTokens": response.usage.prompt_tokens,
                "completionTokens": response.usage.completion_tokens,
            },
            "specArtifactId": spec_art.id,
            "specVersion": spec_art.version,
        }
        if previous is not None:
            metadata["revisionOf"] = previous.id
        language = request.input.get("language")
        if isinstance(language, str) and language.strip():
            metadata["language"] = language
        return metadata

    @staticmethod
    def _validate_linked_spec_section(reply: str, spec_art: Artifact) -> list[str]:
        """Validate that the 'Linked SPEC' section in the LLM output matches
        the input SPEC artifact.

        Returns a list of issue strings (empty if valid).
        """
        return _linked_spec_issues(reply, spec_art)
