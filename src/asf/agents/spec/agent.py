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
    check_attempt,
    check_language,
    is_positive_version,
)
from asf.agents._shared.routing import tier_metadata
from asf.agents.base import AgentRuntime, BaseAgent, Issue
from asf.agents.spec.prompts import (
    SpecPromptContext,
    SpecPrompts,
    SpecTemplate,
    build_spec_messages,
)
from asf.contracts.models import (
    AgentMetadata,
    AgentRequest,
    Artifact,
    ModelMessage,
    ModelRequest,
    ModelResponse,
)

__all__ = ["MAX_REQUIREMENT_CHARS", "SpecAgent", "SpecSettings"]

# Generous on purpose: users paste whole briefs/test-case documents as
# the requirement. 200k chars matches the task agent's text cap
# (MAX_TASK_TEXT_CHARS); the old 20k cap failed real first runs.
MAX_REQUIREMENT_CHARS: int = 200_000


@dataclass(frozen=True)
class SpecSettings:
    prompts: SpecPrompts
    template: SpecTemplate
    model: str | None = None
    parameters: Mapping[str, Any] | None = None


def _check_requirement(request: AgentRequest) -> list[Issue]:
    if "requirement" not in request.input:
        return [Issue("input.requirement", "Missing requirement in input")]
    requirement = request.input["requirement"]
    if not isinstance(requirement, str):
        return [Issue("input.requirement", "input.requirement must be a string")]
    if not requirement.strip():
        return [Issue("input.requirement", "input.requirement must be non-empty")]
    if len(requirement) > MAX_REQUIREMENT_CHARS:
        message = f"input.requirement exceeds maximum length of {MAX_REQUIREMENT_CHARS} characters"
        return [Issue("input.requirement", message)]
    return []


def _check_spec_count(request: AgentRequest) -> list[Issue]:
    if len(artifacts_of(request, "SPEC")) > 1:
        return [Issue("artifacts", "At most one artifact of type SPEC is permitted")]
    return []


def _check_revision_feedback(request: AgentRequest) -> list[Issue]:
    if artifacts_of(request, "SPEC") and not request.feedback:
        message = "Reviewer feedback is required when revising a specification"
        return [Issue("feedback", message)]
    return []


def _check_revision_content(request: AgentRequest, index: int) -> list[Issue]:
    spec_art = request.artifacts[index]
    content = spec_art.content
    text = content.get("text") if isinstance(content, dict) else None
    if not isinstance(text, str) or not text.strip():
        message = "SPEC artifact must have inline content mapping with non-empty 'text'"
        return [Issue(f"artifacts[{index}].content.text", message)]
    return []


def _check_revision_version(request: AgentRequest, index: int) -> list[Issue]:
    version = request.artifacts[index].version
    if is_positive_version(version):
        return []
    message = f"SPEC artifact version '{version}' must match '^[1-9][0-9]*$'"
    return [Issue(f"artifacts[{index}].version", message)]


def _check_revision(request: AgentRequest) -> list[Issue]:
    spec_arts = artifacts_of(request, "SPEC")
    if len(spec_arts) != 1:
        return []
    index = request.artifacts.index(spec_arts[0])
    return [
        *_check_revision_feedback(request),
        *_check_revision_content(request, index),
        *_check_revision_version(request, index),
    ]


def _check_orphan_feedback(request: AgentRequest) -> list[Issue]:
    if request.feedback and not artifacts_of(request, "SPEC"):
        message = "feedback provided without a previous SPEC artifact to revise"
        return [Issue("artifacts", message)]
    return []


def _previous_spec(request: AgentRequest) -> Artifact | None:
    spec_arts = artifacts_of(request, "SPEC")
    return spec_arts[0] if len(spec_arts) == 1 else None


def _previous_spec_text(previous: Artifact | None) -> tuple[str, str] | None:
    if previous is None or not isinstance(previous.content, dict):
        return None
    if "text" not in previous.content:
        return None
    return (previous.version, previous.content["text"])


class SpecAgent(BaseAgent):
    """Agent responsible for creating and revising software specifications."""

    def __init__(self, runtime: AgentRuntime, settings: SpecSettings) -> None:
        super().__init__(runtime)
        self._prompts = settings.prompts
        self._template = settings.template
        self._model = settings.model
        self._parameters = dict(settings.parameters or {})
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
        spec_arts = artifacts_of(request, "SPEC")
        if spec_arts:
            try:
                return int(spec_arts[0].version)
            except (ValueError, TypeError):
                return 0
        return 0

    def _check(self, request: AgentRequest) -> list[Issue]:
        agent_id_message = f"agentId '{request.agent_id}' does not match '{self.metadata.id}'"
        validators = [
            lambda: check_agent_id(request, self.metadata.id, agent_id_message),
            lambda: _check_requirement(request),
            lambda: check_language(request, "input.language must be a non-empty string"),
            lambda: _check_spec_count(request),
            lambda: _check_revision(request),
            lambda: _check_orphan_feedback(request),
            lambda: check_attempt(request),
        ]
        return [issue for validate in validators for issue in validate()]

    def _run(self, request: AgentRequest) -> tuple[dict[str, Any], list[Artifact]]:
        previous = _previous_spec(request)
        messages = self._build_messages(request, previous)
        response = call_model(self._runtime.models, self._model_request(request, messages))
        reply = self._checked_reply(response)
        return self._assemble(request, previous, reply, response)

    def _build_messages(
        self, request: AgentRequest, previous: Artifact | None
    ) -> list[ModelMessage]:
        context = SpecPromptContext(
            prompts=self._prompts,
            template=self._template,
            requirement=request.input["requirement"].strip(),
            language=request.input.get("language"),
            project_context=request.context.get("project"),
            previous_spec=_previous_spec_text(previous),
            feedback=request.feedback,
        )
        return build_spec_messages(context)

    def _model_request(self, request: AgentRequest, messages: list[ModelMessage]) -> ModelRequest:
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

    def _checked_reply(self, response: ModelResponse) -> str:
        reply = unwrap_code_fence(response.content.strip())
        if not reply:
            raise invalid_response("Model returned an empty response")
        headings = heading_lines(reply)
        missing = [s for s in self._template.required_sections if s not in headings]
        if missing:
            raise invalid_response(
                f"Model response is missing required template sections: {missing}",
                details={"missingSections": missing},
            )
        return reply

    def _assemble(
        self,
        request: AgentRequest,
        previous: Artifact | None,
        reply: str,
        response: ModelResponse,
    ) -> tuple[dict[str, Any], list[Artifact]]:
        is_revision = previous is not None
        version = str(int(previous.version) + 1) if previous is not None else "1"
        art_metadata = self._artifact_metadata(request, previous, response)
        artifact = Artifact(
            id=self._runtime.new_id(),
            type="SPEC",
            name="SPEC.md",
            version=version,
            content={"format": "markdown", "text": reply},
            created_by=self.metadata.id,
            created_at=datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
            metadata=art_metadata,
        )
        summary = "Specification revised" if is_revision else "Specification created"
        output = {"summary": summary, "artifactId": artifact.id, "version": version}
        return output, [artifact]

    def _artifact_metadata(
        self,
        request: AgentRequest,
        previous: Artifact | None,
        response: ModelResponse,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "template": "spec",
            "model": response.model,
            "usage": {
                "promptTokens": response.usage.prompt_tokens,
                "completionTokens": response.usage.completion_tokens,
            },
        }
        if previous is not None:
            metadata["revisionOf"] = previous.id
        language = request.input.get("language")
        if isinstance(language, str) and language.strip():
            metadata["language"] = language
        return metadata
