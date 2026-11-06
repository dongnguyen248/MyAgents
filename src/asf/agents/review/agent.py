from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from asf.agents._shared.code_agents import (
    MAX_REPLY_CHARS,
    MAX_TEXT_CHARS,
    CodeRequestRules,
    artifact_of,
    check_code_request,
    code_changeset,
    invalid_response,
    linked_metadata,
)
from asf.agents._shared.model_call import call_model
from asf.agents._shared.parsing import strip_code_fence
from asf.agents._shared.routing import tier_metadata
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

logger = logging.getLogger(__name__)


def _schema_problems(exc: Exception) -> str:
    """Field locations and error kinds from a validation failure.

    Input values are deliberately excluded (``include_input=False``):
    the model reply is untrusted content and must not be echoed, but
    "findings.0.line: int_parsing" is exactly what an operator needs
    to tell a truncated reply from a wrong-typed field.
    """
    if isinstance(exc, ValidationError):
        parts = []
        for entry in exc.errors(include_input=False):
            loc = ".".join(str(part) for part in entry["loc"]) or "(root)"
            parts.append(f"{loc}: {entry['type']}")
        return "; ".join(parts[:5])[:400] or "unparseable reply"
    return type(exc).__name__


class ReviewAgent(BaseAgent):
    """Review a single CODE artifact without repository or sandbox access."""

    def __init__(
        self,
        runtime: AgentRuntime,
        *,
        prompts: ReviewPrompts,
        model: str | None = None,
        parameters: Mapping[str, Any] | None = None,
        skip_when_tests_pass: bool = False,
        max_diff_lines: int = 200,
        report_tail_lines: int = 120,
    ) -> None:
        super().__init__(runtime)
        self._prompts = prompts
        self._model = model
        self._parameters = dict(parameters or {})
        self._skip_when_tests_pass = skip_when_tests_pass
        self._max_diff_lines = max_diff_lines
        self._report_tail_lines = report_tail_lines
        self._metadata = AgentMetadata(
            id="agent-review",
            name="Review Agent",
            type="review",
            version="1.0.0",
            status="IDLE",
            capabilities=["review-code"],
            configuration={},
        )

    @property
    def metadata(self) -> AgentMetadata:
        return self._metadata

    def _check(self, request: AgentRequest) -> list[Issue]:
        return check_code_request(
            request,
            CodeRequestRules(
                agent_id=self.metadata.id,
                required={"SPEC", "PLAN", "TASK", "CODE"},
                optional={"TEST_REPORT"},
            ),
        )

    def _skipped_review(
        self,
        request: AgentRequest,
        code: Artifact,
        changes: Any,
    ) -> tuple[Any, list[Artifact]] | None:
        """The configured fast path: tests already passed on THIS
        code version and the change is small, so the LLM review is
        replaced by a recorded APPROVE (the output says it was
        skipped, and why). Returns None when the fast path does not
        apply. Diff size counts content lines of create/modify
        changes (deletes count 0) — an over-estimate for modifies,
        which only makes the gate more conservative."""
        report = next(
            (
                artifact
                for artifact in request.artifacts
                if artifact.type == "TEST_REPORT"
                and artifact.metadata.get("codeArtifactId") == code.id
                and artifact.metadata.get("codeVersion") == code.version
            ),
            None,
        )
        if report is None or not isinstance(report.content, dict):
            return None
        inner = report.content.get("report")
        if not isinstance(inner, dict) or inner.get("verdict") != "PASS":
            return None
        diff_lines = sum(
            len(change.content.splitlines())
            for change in changes.changes
            if change.operation in ("create", "modify") and change.content
        )
        if diff_lines > self._max_diff_lines:
            return None
        review = ReviewContent(findings=[], verdict="APPROVE")
        text = render_review_markdown(review, code.id, code.version)
        payload = review.model_dump(mode="json", by_alias=True, exclude_none=True)
        artifact = Artifact(
            id=self._runtime.new_id(),
            type="CODE_REVIEW",
            name="CODE_REVIEW.json",
            version="1",
            content={"format": "json", "review": payload, "text": text},
            created_by=self.metadata.id,
            created_at=self._runtime.clock(),
            metadata=linked_metadata(request, code),
        )
        return {
            "verdict": "APPROVE",
            "skipped": True,
            "skipReason": (
                f"tests passed for this code version and the change"
                f" is small ({diff_lines} lines <= {self._max_diff_lines})"
            ),
        }, [artifact]

    def _run(self, request: AgentRequest) -> tuple[Any, list[Artifact]]:
        code = artifact_of(request, "CODE")
        changes = code_changeset(code)
        if self._skip_when_tests_pass:
            skipped = self._skipped_review(request, code, changes)
            if skipped is not None:
                return skipped
        messages = build_review_messages(
            prompts=self._prompts,
            request=request,
            report_tail_lines=self._report_tail_lines,
        )
        try:
            response = call_model(
                self._runtime.models,
                ModelRequest(
                    messages=messages,
                    model=self._model,
                    parameters=dict(self._parameters),
                    metadata={
                        "requestId": request.request_id,
                        "agentId": self.metadata.id,
                        "cachePrefixMessages": 1,
                        "taskItemId": request.input["taskItemId"],
                        **tier_metadata(request.context),
                    },
                ),
            )
        except ModelGatewayError as exc:
            if exc.code == "LLM_INVALID_RESPONSE":
                # Preserve the gateway's own message and details: the
                # gateway raises this code only when a reply arrived
                # but was unusable, and its message says why. Retryable
                # per the shared invalid-response policy.
                raise invalid_response(exc.message, details=exc.details) from None
            raise

        raw = response.content
        if len(raw) > MAX_REPLY_CHARS or not raw.strip():
            raise invalid_response("Review response is empty or exceeds the size limit")
        try:
            review = ReviewContent.model_validate_json(strip_code_fence(raw))
        except (ValueError, ValidationError, RecursionError) as exc:
            # The result keeps its no-echo contract (no model content
            # in error details), so the specific problem goes to the
            # backend log instead: field locations and error kinds
            # only, never input values.
            logger.warning(
                "review reply rejected: %s (replyChars=%d finishReason=%s)",
                _schema_problems(exc),
                len(raw),
                response.finish_reason,
            )
            raise invalid_response("Review response does not match the required schema") from None
        allowed_paths = {change.path for change in changes.changes}
        if any(finding.path not in allowed_paths for finding in review.findings):
            outside = sorted({f.path for f in review.findings if f.path not in allowed_paths})
            logger.warning("review findings reference paths outside CODE: %s", outside[:5])
            raise invalid_response("Review finding references a path outside CODE")
        text = render_review_markdown(review, code.id, code.version)
        if len(text) > MAX_TEXT_CHARS:
            raise invalid_response("Rendered review exceeds the size limit")
        payload = review.model_dump(mode="json", by_alias=True, exclude_none=True)
        artifact = Artifact(
            id=self._runtime.new_id(),
            type="CODE_REVIEW",
            name="CODE_REVIEW.json",
            version="1",
            content={"format": "json", "review": payload, "text": text},
            created_by=self.metadata.id,
            created_at=self._runtime.clock(),
            metadata=linked_metadata(request, code),
        )
        return {"verdict": review.verdict}, [artifact]
