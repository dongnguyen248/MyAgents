"""Applying AI review results (Phase 12).

The apply half of the AI review loop, split from ``ai_review`` for
size: :class:`AiReviewApply` runs inside the tick's commit phase,
after the claim token has been re-validated. It persists the review
artifact, re-derives the verdict in code from the findings, and
records the decision as reviewer ``ai-reviewer`` through the
ApprovalService — so revision counting, producer feedback and
escalation keep flowing through the state machine exactly as they
do for a human decider. A decision that landed while the reviewer
ran (a human override) wins: the apply stands down and lets the
normal approval sync consume it.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from asf.agents._shared.security import redact_text
from asf.agents.artifact_review.prompts import ArtifactReviewContent
from asf.agents.artifact_review.render import render_feedback
from asf.agents.artifact_review.verdict import (
    RoundOutcome,
    artifact_hash,
    derive_verdict,
    detect_regression,
    detect_stagnation,
)
from asf.approval.mode import ResolvedApproval
from asf.contracts.models import AgentResult, PlatformError
from asf.orchestrator.ai_review import (
    MAX_REVIEW_ATTEMPTS,
    REVIEW_ARTIFACT_TYPE,
    REVIEW_RETRY_DELAY_SECONDS,
    AiReviewStage,
    Escalation,
    _review_content,
    ai_stage,
)
from asf.orchestrator.execution import Observation, WorkflowExecution
from asf.workflow.definition import WorkflowStepDef

if TYPE_CHECKING:
    from asf.orchestrator.engine import Orchestrator

__all__ = ["AiReviewApply", "apply_review_result"]

_UNREADABLE_RESULT_COMMENT = "AI reviewer returned an unreadable result; escalating to a human."

#: Cap for the reviewer error message carried on the escalation
#: event: long enough to name the fix, short enough for a panel.
_ERROR_MESSAGE_LIMIT = 240


def _short_error_message(error: PlatformError) -> str:
    """The error's message made safe and short for the escalation
    event: redacted first, so a secret the cap would cut in half
    cannot survive in truncated form."""
    return redact_text(error.message)[:_ERROR_MESSAGE_LIMIT]


def apply_review_result(
    engine: Orchestrator, run: WorkflowExecution, result: AgentResult | None
) -> None:
    """Apply a claimed dispatch's review result, if it produced one."""
    if result is not None:
        AiReviewApply(engine).apply(run, result)


class AiReviewApply:
    """Commit-phase applier for one engine's AI review results."""

    def __init__(self, engine: Orchestrator) -> None:
        self._engine = engine
        self._stage: AiReviewStage = ai_stage(engine)

    def apply(self, run: WorkflowExecution, result: AgentResult) -> None:
        """Apply one reviewer result inside the tick's commit phase."""
        engine = self._engine
        step = engine._step(run)
        self._record_result(run, result)
        if result.status != "SUCCESS" or result.errors:
            if not self._superseded(run):
                self._apply_failure(run, step, result)
            return
        content = self._result_content(result)
        if content is None:
            self._escalate_unreadable(run, step)
            return
        resolved = self._stage.resolved(run, step)
        verdict = derive_verdict(
            list(content.findings),
            resolved.block_on,
            round_number=self._stage._round_number(run, step),
        )
        engine._publish_artifacts(run, result)
        self._event_completed(run, step, content, verdict)
        if self._superseded(run):
            return
        if verdict == "APPROVE":
            self._stage._decide(run, "APPROVED", _approval_comment(content))
            engine._sync_approval(run)
            return
        self._apply_changes_requested(run, step, resolved, content)

    def _record_result(self, run: WorkflowExecution, result: AgentResult) -> None:
        run.results.append(result.model_copy(deep=True))
        for event in result.events:
            run.observations.append(Observation(id=event.id, event=event.model_copy(deep=True)))
        run.observations.append(
            Observation(id=result.request_id + ":metrics", result=result.model_copy(deep=True))
        )

    def _result_content(self, result: AgentResult) -> ArtifactReviewContent | None:
        artifact = next(
            (item for item in result.artifacts if item.type == REVIEW_ARTIFACT_TYPE), None
        )
        if artifact is None:
            return None
        return _review_content(artifact)

    def _event_completed(
        self,
        run: WorkflowExecution,
        step: WorkflowStepDef,
        content: ArtifactReviewContent,
        verdict: str,
    ) -> None:
        self._engine._event(
            run,
            "AI_REVIEW_COMPLETED",
            f"AI review of {step.name} completed (round {self._stage._round_number(run, step)})",
            metadata={
                "stepId": step.id,
                "stage": step.stage.lower(),
                "round": self._stage._round_number(run, step),
                "verdict": verdict,
                "counts": _severity_counts(content),
            },
        )

    def _superseded(self, run: WorkflowExecution) -> bool:
        """True when a decision landed while the reviewer ran: apply
        that decision through the normal sync and stand down."""
        engine = self._engine
        if run.approval_id is None:
            return True
        service, _ = engine._approval_dependencies()
        if service.get(run.approval_id).status == "PENDING":
            return False
        engine._sync_approval(run)
        return True

    def _escalate_unreadable(self, run: WorkflowExecution, step: WorkflowStepDef) -> None:
        self._stage._escalate(
            run,
            step,
            Escalation(reason="REVIEWER_FAILED", comment=_UNREADABLE_RESULT_COMMENT),
        )

    def _apply_failure(
        self, run: WorkflowExecution, step: WorkflowStepDef, result: AgentResult
    ) -> None:
        key = f"ai-review:{run.approval_id}"
        attempts = run.attempts.get(key, 0) + 1
        run.attempts[key] = attempts
        if attempts < MAX_REVIEW_ATTEMPTS:
            delay = timedelta(seconds=REVIEW_RETRY_DELAY_SECONDS)
            run.retry_at = self._engine._now() + delay
            return
        summary = "; ".join(f"{error.code}: {error.message}" for error in result.errors)
        first = result.errors[0] if result.errors else None
        self._stage._escalate(
            run,
            step,
            Escalation(
                reason="REVIEWER_FAILED",
                comment=(
                    f"AI reviewer failed after {attempts} attempts: {summary or 'unknown error'}"
                ),
                error_code=first.code if first is not None else None,
                error_message=_short_error_message(first) if first is not None else None,
            ),
        )

    def _apply_changes_requested(
        self,
        run: WorkflowExecution,
        step: WorkflowStepDef,
        resolved: ResolvedApproval,
        content: ArtifactReviewContent,
    ) -> None:
        engine = self._engine
        previous = self._previous_outcome(run, step)
        current = RoundOutcome(
            findings=tuple(content.findings),
            artifact_hash=artifact_hash(run.artifacts[step.produces[0]]),
        )
        feedback = render_feedback(list(content.findings), _regressions(previous, content))
        # Exhaustion is checked first: at the revision limit the
        # project's onExhausted choice governs, while stagnation is
        # the early stop for rounds that still have revisions left.
        if run.state.revisions.get(step.id, 0) >= self._effective_max(run, step, resolved):
            if resolved.on_exhausted == "accept_with_warnings":
                self._accept_with_warnings(run, step, content)
                return
            self._stage._escalate(run, step, Escalation(reason="MAX_REVISIONS", comment=feedback))
            return
        if previous is not None and detect_stagnation(
            previous, current, block_on=resolved.block_on
        ):
            self._escalate_no_progress(run, step, feedback)
            return
        self._stage._decide(run, "REQUEST_CHANGES", feedback or content.summary)
        engine._sync_approval(run)

    def _escalate_no_progress(
        self, run: WorkflowExecution, step: WorkflowStepDef, feedback: str
    ) -> None:
        self._engine._event(
            run,
            "AI_REVIEW_STAGNATION",
            f"AI review of {step.name} made no progress on the blocking findings",
            metadata={"stepId": step.id, "stage": step.stage.lower()},
        )
        self._stage._escalate(run, step, Escalation(reason="NO_PROGRESS", comment=feedback))

    def _previous_outcome(
        self, run: WorkflowExecution, step: WorkflowStepDef
    ) -> RoundOutcome | None:
        previous = self._stage._previous_review(run, step)
        if previous is None:
            return None
        content = _review_content(previous)
        if content is None:
            return None
        reviewed = next(
            (
                artifact
                for artifact in run.artifact_history.values()
                if artifact.id == previous.metadata.get("reviewedArtifactId")
                and artifact.version == previous.metadata.get("reviewedArtifactVersion")
            ),
            None,
        )
        return RoundOutcome(
            findings=tuple(content.findings),
            artifact_hash=artifact_hash(reviewed) if reviewed is not None else "",
        )

    def _effective_max(
        self, run: WorkflowExecution, step: WorkflowStepDef, resolved: ResolvedApproval
    ) -> int:
        graph_max = self._engine._graph.max_revisions.get(step.id, resolved.max_revisions)
        return min(resolved.max_revisions, graph_max)

    def _accept_with_warnings(
        self, run: WorkflowExecution, step: WorkflowStepDef, content: ArtifactReviewContent
    ) -> None:
        engine = self._engine
        open_findings = render_feedback(list(content.findings), [])
        comment = "AI review accepted with warnings (onExhausted: accept_with_warnings)."
        if open_findings:
            comment += "\nStill open:\n" + open_findings
        self._stage._decide(run, "APPROVED", comment)
        engine._event(
            run,
            "AI_REVIEW_ACCEPTED_WITH_WARNINGS",
            f"AI review of {step.name} accepted with warnings at the revision limit",
            metadata={"stepId": step.id, "stage": step.stage.lower()},
        )
        engine._sync_approval(run)


def _regressions(previous: RoundOutcome | None, content: ArtifactReviewContent) -> list[str]:
    if previous is None:
        return []
    return detect_regression(list(previous.findings), list(content.findings))


def _severity_counts(content: ArtifactReviewContent) -> dict[str, int]:
    counts = {"BLOCKER": 0, "MAJOR": 0, "MINOR": 0, "NIT": 0}
    for finding in content.findings:
        counts[finding.severity] += 1
    return counts


def _approval_comment(content: ArtifactReviewContent) -> str:
    comment = content.summary
    non_blocking = render_feedback(list(content.findings), [])
    if non_blocking:
        comment += "\nNon-blocking findings:\n" + non_blocking
    return comment
