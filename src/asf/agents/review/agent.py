from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from asf.agents._shared.code_agents import (
    MAX_REPLY_CHARS,
    MAX_TEXT_CHARS,
    artifact_of,
    check_code_request,
    code_changeset,
    invalid_response,
    linked_metadata,
)
from asf.agents._shared.parsing import strip_code_fence
from asf.agents.base import AgentRuntime, BaseAgent, Issue
from asf.agents.review.prompts import (
    MAX_FINDINGS,
    Finding,
    ReviewContent,
    ReviewPrompts,
    build_review_messages,
    render_review_markdown,
)
from asf.contracts.models import AgentMetadata, AgentRequest, Artifact, ModelRequest
from asf.models.errors import ModelGatewayError

__all__ = ["MAX_FINDINGS", "Finding", "ReviewAgent", "ReviewContent", "render_review_markdown"]


class ReviewAgent(BaseAgent):
    """Review a single CODE artifact without repository or sandbox access."""

    def __init__(
        self,
        runtime: AgentRuntime,
        *,
        prompts: ReviewPrompts,
        model: str | None = None,
        parameters: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(runtime)
        self._prompts = prompts
        self._model = model
        self._parameters = dict(parameters or {})
        self._metadata = AgentMetadata(
            id="agent-review", name="Review Agent", type="review", version="1.0.0",
            status="IDLE", capabilities=["review-code"], configuration={},
        )

    @property
    def metadata(self) -> AgentMetadata:
        return self._metadata

    def _check(self, request: AgentRequest) -> list[Issue]:
        return check_code_request(
            request, self.metadata.id, required={"SPEC", "PLAN", "TASK", "CODE"}
        )

    def _run(self, request: AgentRequest) -> tuple[Any, list[Artifact]]:
        code = artifact_of(request, "CODE")
        changes = code_changeset(code)
        messages = build_review_messages(prompts=self._prompts, request=request)
        try:
            response = self._runtime.models.complete(ModelRequest(
                messages=messages,
                model=self._model,
                parameters=dict(self._parameters),
                metadata={
                    "requestId": request.request_id, "agentId": self.metadata.id,
                    "taskItemId": request.input["taskItemId"],
                },
            ))
        except ModelGatewayError as exc:
            if exc.code == "LLM_INVALID_RESPONSE":
                raise invalid_response("Model returned an invalid review response") from None
            raise

        raw = response.content
        if len(raw) > MAX_REPLY_CHARS or not raw.strip():
            raise invalid_response("Review response is empty or exceeds the size limit")
        try:
            review = ReviewContent.model_validate_json(strip_code_fence(raw))
        except (ValueError, ValidationError, RecursionError):
            raise invalid_response("Review response does not match the required schema") from None
        allowed_paths = {change.path for change in changes.changes}
        if any(finding.path not in allowed_paths for finding in review.findings):
            raise invalid_response("Review finding references a path outside CODE")
        text = render_review_markdown(review, code.id, code.version)
        if len(text) > MAX_TEXT_CHARS:
            raise invalid_response("Rendered review exceeds the size limit")
        payload = review.model_dump(mode="json", by_alias=True, exclude_none=True)
        artifact = Artifact(
            id=self._runtime.new_id(), type="CODE_REVIEW", name="CODE_REVIEW.json", version="1",
            content={"format": "json", "review": payload, "text": text},
            created_by=self.metadata.id, created_at=self._runtime.clock(),
            metadata=linked_metadata(request, code),
        )
        return {"verdict": review.verdict}, [artifact]
