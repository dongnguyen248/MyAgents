from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from pydantic_core import ErrorDetails

from asf.agents._shared.code_agents import MAX_REPLY_CHARS, MAX_TEXT_CHARS, linked_metadata
from asf.agents._shared.harness import HarnessComponents, fingerprint
from asf.agents._shared.model_call import call_model
from asf.agents._shared.model_errors import invalid_response
from asf.agents._shared.parsing import strip_code_fence
from asf.agents._shared.routing import tier_metadata
from asf.agents._shared.security import redact_text
from asf.agents.artifact_review.checks import DEFAULT_MAX_TASKS, run_mechanical_checks
from asf.agents.artifact_review.prompts import (
    MAX_FINDINGS,
    STAGE_TYPES,
    UPSTREAM_TYPES,
    ArtifactReviewContent,
    ArtifactReviewPrompts,
    Finding,
    ReviewTarget,
    artifacts_of,
    build_artifact_review_messages,
    review_target,
    round_of,
    stage_of,
)
from asf.agents.artifact_review.render import render_review_markdown
from asf.agents.artifact_review.verdict import (
    DEFAULT_BLOCK_ON,
    derive_verdict,
    merge_findings,
)
from asf.agents.base import AgentRuntime, BaseAgent, Issue
from asf.contracts.models import (
    AgentMetadata,
    AgentRequest,
    Artifact,
    ModelMessage,
    ModelRequest,
    ModelResponse,
)
from asf.models.errors import ModelGatewayError

__all__ = ["ArtifactReviewAgent", "ArtifactReviewSettings"]

logger = logging.getLogger(__name__)

SEVERITY_ORDER = ("BLOCKER", "MAJOR", "MINOR", "NIT")
MECHANICAL_SUMMARY = (
    "Mechanical checks found blocking problems; the AI review was skipped for this round."
)


def _schema_problems(exc: Exception) -> str:
    """Field locations and error kinds only; the reply is untrusted."""
    if isinstance(exc, ValidationError):
        parts = []
        for entry in exc.errors(include_input=False):
            loc = ".".join(str(part) for part in entry["loc"]) or "(root)"
            parts.append(f"{loc}: {entry['type']}")
        return "; ".join(parts[:5])[:400] or "unparseable reply"
    return type(exc).__name__


#: The rejection reason carried in the error: long enough to name
#: the first few problems, short enough for an error banner.
_REASON_LIMIT = 240
_MAX_REASON_PROBLEMS = 3


def _schema_reason(exc: Exception, stripped: str) -> str:
    """A short, operator-actionable reason the reply was rejected.

    Built only from schema facts — field locations, error kinds,
    the schema's own expected values and this package's validator
    messages — never from the reply itself (inputs are excluded
    from the error entries), then redacted and capped.
    """
    if isinstance(exc, RecursionError):
        return "JSON nested too deeply"
    if not isinstance(exc, ValidationError):
        return "not valid JSON"
    parts = [_problem_reason(entry, stripped) for entry in exc.errors(include_input=False)]
    reason = "; ".join(parts[:_MAX_REASON_PROBLEMS])
    extra = len(parts) - _MAX_REASON_PROBLEMS
    if extra > 0:
        reason += f"; and {extra} more"
    return redact_text(reason)[:_REASON_LIMIT] or "not valid JSON"


def _problem_reason(entry: ErrorDetails, stripped: str) -> str:
    loc = ".".join(str(part) for part in entry["loc"])
    kind = entry["type"]
    ctx = entry.get("ctx") or {}
    if kind == "json_invalid":
        return _json_reason(ctx, stripped)
    if kind == "literal_error":
        return f"unknown value at '{loc}' (expected {ctx.get('expected', 'a listed value')})"
    if kind == "value_error":
        return _value_reason(loc, ctx)
    if kind == "too_long":
        return _too_long_reason(loc, ctx)
    return _basic_reason(loc, kind)


def _basic_reason(loc: str, kind: str) -> str:
    if kind == "missing":
        return f"missing field '{loc}'"
    if kind == "extra_forbidden":
        return f"unexpected field '{loc}'"
    if kind.endswith("_type"):
        return f"wrong type at '{loc}'"
    if "too_short" in kind:
        return f"'{loc}' is too short"
    if loc:
        return f"{loc}: {kind}"
    return kind


def _json_reason(ctx: dict[str, Any], stripped: str) -> str:
    if "trailing characters" in str(ctx.get("error", "")):
        return "extra text after the JSON value"
    text = stripped.lstrip()
    if text[:1] not in ("{", "[", '"') and "{" in text:
        return "extra text before the JSON"
    return "not valid JSON"


def _value_reason(loc: str, ctx: dict[str, Any]) -> str:
    message = str(ctx.get("error", "invalid value"))
    if loc:
        return f"{loc}: {message}"
    return message


def _too_long_reason(loc: str, ctx: dict[str, Any]) -> str:
    limit = ctx.get("max_length", "?")
    if ctx.get("field_type") == "List":
        return f"'{loc}' has too many items (max {limit})"
    return f"'{loc}' is too long (max {limit} characters)"


@dataclass(frozen=True)
class _ReviewRecord:
    target: ReviewTarget
    content: ArtifactReviewContent
    text: str
    verdict: str


@dataclass(frozen=True)
class ArtifactReviewSettings:
    prompts: ArtifactReviewPrompts
    model: str | None = None
    parameters: Mapping[str, Any] | None = None
    block_on: tuple[str, ...] = DEFAULT_BLOCK_ON
    max_tasks: int = DEFAULT_MAX_TASKS
    harness: HarnessComponents | None = None
    model_profile: str | None = None


class ArtifactReviewAgent(BaseAgent):
    """Review one SPEC, PLAN or TASK artifact; never writes artifacts."""

    def __init__(self, runtime: AgentRuntime, settings: ArtifactReviewSettings) -> None:
        super().__init__(runtime)
        self._settings = settings
        self._metadata = AgentMetadata(
            id="agent-artifact-review",
            name="Artifact Review Agent",
            type="artifact-review",
            version="1.0.0",
            status="IDLE",
            capabilities=["review-artifacts"],
            configuration=(
                {"modelProfile": settings.model_profile} if settings.model_profile else {}
            ),
        )

    @property
    def metadata(self) -> AgentMetadata:
        return self._metadata

    def _check(self, request: AgentRequest) -> list[Issue]:
        stage = stage_of(request)
        if stage not in STAGE_TYPES:
            return [Issue("input.stage", "input.stage must be one of spec, plan, task")]
        issues: list[Issue] = []
        if round_of(request) < 1:
            issues.append(Issue("input.round", "input.round must be a positive integer"))
        target_type = STAGE_TYPES[stage]
        if len(artifacts_of(request, target_type)) != 1:
            issues.append(Issue("artifacts", f"Exactly one {target_type} artifact is required"))
        for kind in UPSTREAM_TYPES[stage]:
            if len(artifacts_of(request, kind)) != 1:
                issues.append(Issue("artifacts", f"Exactly one {kind} artifact is required"))
        if len(artifacts_of(request, "ARTIFACT_REVIEW")) > 1:
            issues.append(Issue("artifacts", "At most one previous ARTIFACT_REVIEW is permitted"))
        return issues

    def _run(self, request: AgentRequest) -> tuple[Any, list[Artifact]]:
        target = review_target(request)
        upstream = {artifact.type: artifact for artifact in target.upstream}
        mechanical = run_mechanical_checks(
            target.stage, target.artifact, upstream, max_tasks=self._settings.max_tasks
        )
        if any(finding.severity == "BLOCKER" for finding in mechanical):
            content = ArtifactReviewContent(findings=mechanical, summary=MECHANICAL_SUMMARY)
            return self._assemble(request, target, content)
        messages = build_artifact_review_messages(
            prompts=self._settings.prompts,
            request=request,
            target=target,
            harness=self._settings.harness,
        )
        review = _parse_review(self._call_model(request, messages))
        previous = _previous_ai_findings(target)
        merged = merge_findings(previous, list(review.findings))
        content = ArtifactReviewContent.model_construct(
            findings=_cap_findings([*mechanical, *merged]),
            summary=review.summary,
        )
        return self._assemble(request, target, content)

    def _call_model(self, request: AgentRequest, messages: list[ModelMessage]) -> ModelResponse:
        try:
            return call_model(
                self._runtime.models,
                ModelRequest(
                    messages=messages,
                    model=self._settings.model,
                    parameters=dict(self._settings.parameters or {}),
                    metadata={
                        "requestId": request.request_id,
                        "agentId": self.metadata.id,
                        "cachePrefixMessages": 1,
                        **tier_metadata(request.context),
                    },
                ),
            )
        except ModelGatewayError as exc:
            if exc.code == "LLM_INVALID_RESPONSE":
                raise invalid_response(exc.message, details=exc.details) from None
            raise

    def _assemble(
        self, request: AgentRequest, target: ReviewTarget, content: ArtifactReviewContent
    ) -> tuple[Any, list[Artifact]]:
        verdict = derive_verdict(
            list(content.findings),
            _block_on_of(request, self._settings.block_on),
            round_number=target.round_number,
        )
        text = render_review_markdown(content, target=target, verdict=verdict)
        if len(text) > MAX_TEXT_CHARS:
            raise invalid_response("Rendered artifact review exceeds the size limit")
        record = _ReviewRecord(target=target, content=content, text=text, verdict=verdict)
        artifact = self._review_artifact(request, record)
        output = {
            "verdict": verdict,
            "stage": target.stage,
            "round": target.round_number,
            "findings": len(content.findings),
        }
        return output, [artifact]

    def _harness_fingerprint(self) -> str:
        components = self._settings.harness or self._settings.prompts.to_components()
        return fingerprint(components)

    def _review_artifact(self, request: AgentRequest, record: _ReviewRecord) -> Artifact:
        target = record.target
        content = record.content
        payload = content.model_dump(mode="json", by_alias=True, exclude_none=True)
        counts = {
            severity: sum(1 for f in content.findings if f.severity == severity)
            for severity in SEVERITY_ORDER
        }
        return Artifact(
            id=self._runtime.new_id(),
            type="ARTIFACT_REVIEW",
            name="ARTIFACT_REVIEW.json",
            version="1",
            content={"format": "json", "review": payload, "text": record.text},
            created_by=self.metadata.id,
            created_at=self._runtime.clock(),
            metadata={
                **linked_metadata(request, target.artifact),
                "reviewedArtifactId": target.artifact.id,
                "reviewedArtifactVersion": target.artifact.version,
                "stage": target.stage,
                "round": target.round_number,
                "verdict": record.verdict,
                "findingCounts": counts,
                "findingIds": [finding.id for finding in content.findings],
                "harnessFingerprint": self._harness_fingerprint(),
            },
        )


def _previous_ai_findings(target: ReviewTarget) -> list[Finding]:
    if target.previous is None:
        return []
    # Mechanical findings are recomputed every round; carrying them
    # forward would duplicate them under the same deterministic ids.
    return [finding for finding in target.previous.findings if finding.source == "ai"]


def _block_on_of(request: AgentRequest, fallback: tuple[str, ...]) -> tuple[str, ...]:
    """Per-request blocking severities from the orchestrator, if valid.

    The resolved project configuration travels in the request input
    because the agent's own settings are platform-wide; an unusable
    value falls back to the settings rather than failing the review.
    """
    raw = request.input.get("blockOn")
    if not isinstance(raw, list) or not raw:
        return fallback
    known = ("BLOCKER", "MAJOR", "MINOR", "NIT")
    if any(item not in known for item in raw):
        return fallback
    severities = tuple(dict.fromkeys(raw))
    return ("BLOCKER", *(item for item in severities if item != "BLOCKER"))


def _cap_findings(findings: list[Finding]) -> list[Finding]:
    if len(findings) <= MAX_FINDINGS:
        return findings
    ranked = sorted(range(len(findings)), key=lambda i: SEVERITY_ORDER.index(findings[i].severity))
    keep = sorted(ranked[:MAX_FINDINGS])
    return [findings[i] for i in keep]


def _parse_review(response: ModelResponse) -> ArtifactReviewContent:
    raw = response.content
    if len(raw) > MAX_REPLY_CHARS or not raw.strip():
        raise invalid_response("Artifact review response is empty or exceeds the size limit")
    stripped = strip_code_fence(raw)
    try:
        return ArtifactReviewContent.model_validate_json(stripped)
    except (ValueError, ValidationError, RecursionError) as exc:
        logger.warning(
            "artifact review reply rejected: %s (replyChars=%d finishReason=%s)",
            _schema_problems(exc),
            len(raw),
            response.finish_reason,
        )
        reason = _schema_reason(exc, stripped)
        raise invalid_response(
            f"Artifact review response does not match the required schema: {reason}",
            details={"reason": reason},
        ) from None
