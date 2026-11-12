"""The AI review loop for approval gates (Phase 12).

``AiReviewStage`` is the orchestrator's automatic decider for gated
steps whose resolved approval mode is ``ai``. At an ``X_REVIEW`` stage
it claims and dispatches the artifact-review agent under the tick's
``in_flight`` token; applying the result lives in
``ai_review_apply`` (kept separate so neither module grows past the
code-structure limits). Decisions are recorded as reviewer
``ai-reviewer`` through the existing ApprovalService, so revision
counting, producer feedback and escalation keep flowing through the
state machine exactly as they do for a human decider. The stage
object is stateless (all state lives on the run and in the approval
service), so the engine builds one per use via :func:`ai_stage`.
"""

from __future__ import annotations

import logging
from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from asf.agents.artifact_review.prompts import ArtifactReviewContent
from asf.approval.mode import (
    ResolvedApproval,
    approval_overrides_from_context,
    approval_policy_from_context,
    max_review_rounds_from_context,
    resolve_approval_mode,
)
from asf.approval.models import AI_REVIEWER, ApprovalDecision, ApprovalPolicy, ApprovalSpec
from asf.contracts.models import (
    AgentRequest,
    AgentResult,
    Artifact,
    PlatformError,
    RunMetrics,
)
from asf.orchestrator.execution import WorkflowExecution
from asf.state_machine.machine import RunState
from asf.state_machine.status import kind_of
from asf.state_machine.triggers import StageKind
from asf.workflow.definition import WorkflowStepDef

if TYPE_CHECKING:
    from asf.orchestrator.engine import Orchestrator

__all__ = ["AiReviewStage", "ai_stage", "dispatch_claimed", "skip_approvals"]

logger = logging.getLogger("asf.orchestrator.ai_review")

REVIEW_AGENT_TYPE = "artifact-review"
REVIEW_ARTIFACT_TYPE = "ARTIFACT_REVIEW"
FALLBACK_REVIEWER_ID = "agent-artifact-review"
MAX_REVIEW_ATTEMPTS = 2
REVIEW_RETRY_DELAY_SECONDS = 5
UPSTREAM_TYPES = {"SPEC": (), "PLAN": ("SPEC",), "TASK": ("SPEC", "PLAN")}

_BUDGET_COMMENT = "AI review round budget exhausted (maxReviewRounds); escalating to a human."


@dataclass(frozen=True)
class Escalation:
    """An AI-review escalation: its audit reason, the decision
    comment, and — for a reviewer failure — the terminal error's
    code and redacted message, carried on the escalation event so
    the operator sees the cause, not just the reason. When the
    failure came from a provider call, the provider's own message
    (from the error's details, already redacted and capped at its
    source) rides along the same way."""

    reason: str
    comment: str
    error_code: str | None = None
    error_message: str | None = None
    provider_message: str | None = None


def ai_stage(engine: Orchestrator) -> AiReviewStage:
    """The engine's AI review collaborator (stateless; built per use)."""
    return AiReviewStage(engine)


def dispatch_claimed(engine: Orchestrator, claimed: WorkflowExecution) -> AgentResult | None:
    """Execute one claimed dispatch outside the store transaction.

    AI review stages run the reviewer and hand the result back for
    the commit phase to apply; every other stage dispatches (and
    applies) through the engine as before and returns None.
    """
    if kind_of(engine._graph, claimed.state.stage) == StageKind.REVIEW:
        return ai_stage(engine).execute(claimed)
    engine._dispatch(claimed)
    return None


def skip_approvals(run: WorkflowExecution) -> set[str]:
    """Approval steps this run skips, from its context.

    Set at task creation (context key ``skipApprovals``: step ids
    such as "spec"/"plan"/"task"); validated against the workflow
    definition by the API service before the run starts.
    """
    raw = run.context.get("skipApprovals")
    if isinstance(raw, list):
        return {item for item in raw if isinstance(item, str)}
    return set()


def _review_content(artifact: Artifact) -> ArtifactReviewContent | None:
    """The validated review payload of an ARTIFACT_REVIEW artifact."""
    review = artifact.content.get("review") if isinstance(artifact.content, dict) else None
    if not isinstance(review, dict):
        return None
    try:
        return ArtifactReviewContent.model_validate(review)
    except ValueError:
        return None


class AiReviewStage:
    """Automatic decider for ai-mode approval gates of one engine."""

    def __init__(self, engine: Orchestrator) -> None:
        self._engine = engine

    def resolved(self, run: WorkflowExecution, step: WorkflowStepDef) -> ResolvedApproval:
        """The step's effective gate settings for this run's project."""
        return resolve_approval_mode(step, approval_overrides_from_context(run.context))

    def gate_skipped(self, run: WorkflowExecution, step: WorkflowStepDef) -> bool:
        """True when the gate must not be requested at all: the task
        setting skips it, or the resolved mode is ``none``."""
        if step.id in skip_approvals(run):
            return True
        return self.resolved(run, step).mode == "none"

    def policy_for(
        self, run: WorkflowExecution, spec: ApprovalSpec, base_policy: ApprovalPolicy
    ) -> ApprovalPolicy:
        """The approval policy a new request for this run must snapshot."""
        step = self._step_of(spec)
        if step is not None and self.resolved(run, step).mode == "ai":
            human = approval_policy_from_context(run.context) or base_policy
            reviewers = [AI_REVIEWER, *(r for r in human.reviewers if r != AI_REVIEWER)]
            return ApprovalPolicy(reviewers=reviewers, min_approvals=1)
        return approval_policy_from_context(run.context) or base_policy

    def claim(self, run: WorkflowExecution) -> str | None:
        """Claim a reviewer dispatch for this tick, or None to park.

        Runs inside the tick's claim transaction, after the approval
        state has been synced: the stage may have moved on, the gate
        may be human-mode, a retry backoff may be running, or the
        per-run round budget may be spent (which escalates instead).
        """
        engine = self._engine
        if kind_of(engine._graph, run.state.stage) != StageKind.REVIEW:
            return None
        if run.approval_id is None:
            return None
        step = engine._step(run)
        if self.resolved(run, step).mode != "ai":
            return None
        service, _ = engine._approval_dependencies()
        request = service.get(run.approval_id)
        if request.status != "PENDING" or AI_REVIEWER not in request.reviewers:
            return None
        if run.retry_at is not None and engine._now() < run.retry_at:
            return None
        if self._budget_exhausted(run, step):
            return None
        run.retry_at = None
        run.in_flight = engine._new_id()
        self._event_started(run, step)
        return run.in_flight

    def execute(self, run: WorkflowExecution) -> AgentResult | None:
        """Run the reviewer once, outside any store transaction."""
        engine = self._engine
        step = engine._step(run)
        request_id = run.in_flight or engine._new_id()
        try:
            agent = engine._registry.for_type(REVIEW_AGENT_TYPE)
        except KeyError:
            return self._failed_result(
                request_id,
                FALLBACK_REVIEWER_ID,
                "AGENT_NOT_REGISTERED",
                "No artifact-review agent is registered",
            )
        request = self._build_request(run, step, agent.get_metadata().id)
        self._note_degraded(run, step, request)
        try:
            return agent.execute(request)
        except Exception:
            return self._failed_result(
                request.request_id,
                request.agent_id,
                "AGENT_EXECUTION_FAILED",
                "Artifact review agent raised outside its result contract",
            )

    def _step_of(self, spec: ApprovalSpec) -> WorkflowStepDef | None:
        step_id = spec.metadata.get("stepId")
        for step in self._engine._definition.steps:
            if step.id == step_id:
                return step
        return None

    def _round_number(self, run: WorkflowExecution, step: WorkflowStepDef) -> int:
        return run.state.revisions.get(step.id, 0) + 1

    def _rounds_done(self, run: WorkflowExecution) -> int:
        return sum(
            1 for artifact in run.artifact_history.values() if artifact.type == REVIEW_ARTIFACT_TYPE
        )

    def _budget_exhausted(self, run: WorkflowExecution, step: WorkflowStepDef) -> bool:
        if self._rounds_done(run) < max_review_rounds_from_context(run.context):
            return False
        self._escalate(run, step, Escalation(reason="BUDGET", comment=_BUDGET_COMMENT))
        return True

    def _event_started(self, run: WorkflowExecution, step: WorkflowStepDef) -> None:
        round_number = self._round_number(run, step)
        self._engine._event(
            run,
            "AI_REVIEW_STARTED",
            f"AI review of {step.name} started (round {round_number})",
            metadata={
                "stepId": step.id,
                "stage": step.stage.lower(),
                "round": round_number,
            },
        )

    def _previous_review(self, run: WorkflowExecution, step: WorkflowStepDef) -> Artifact | None:
        # Strictly earlier rounds only: the apply phase publishes the
        # current round's review before comparing against the previous
        # one, and a round must never be compared against itself.
        stage = step.stage.lower()
        current = self._round_number(run, step)
        candidates = [
            artifact
            for artifact in run.artifact_history.values()
            if artifact.type == REVIEW_ARTIFACT_TYPE
            and artifact.metadata.get("stage") == stage
            and int(artifact.metadata.get("round") or 0) < current
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda item: int(item.metadata.get("round") or 0))

    def _build_request(
        self, run: WorkflowExecution, step: WorkflowStepDef, agent_id: str
    ) -> AgentRequest:
        engine = self._engine
        resolved = self.resolved(run, step)
        artifacts = [run.artifacts[step.produces[0]]]
        for kind in UPSTREAM_TYPES[step.stage]:
            if kind in run.artifacts:
                artifacts.append(run.artifacts[kind])
        previous = self._previous_review(run, step)
        if previous is not None:
            artifacts.append(previous)
        return AgentRequest(
            request_id=run.in_flight or engine._new_id(),
            task_id=run.task_id,
            project_id=run.project_id,
            workflow_id=engine._definition.id,
            agent_id=agent_id,
            input={
                "stage": step.stage.lower(),
                "round": self._round_number(run, step),
                "blockOn": list(resolved.block_on),
            },
            context=deepcopy(run.context),
            artifacts=deepcopy(artifacts),
            feedback=[],
            metadata={"runId": run.id, "stepId": step.id},
        )

    def _note_degraded(
        self, run: WorkflowExecution, step: WorkflowStepDef, request: AgentRequest
    ) -> None:
        previous = next((a for a in request.artifacts if a.type == REVIEW_ARTIFACT_TYPE), None)
        if previous is None or _review_content(previous) is not None:
            return
        logger.warning(
            "Previous review artifact %s for run %s is unreadable; reviewing without it",
            previous.id,
            run.id,
        )
        self._engine._event(
            run,
            "AI_REVIEW_DEGRADED",
            "Previous AI review artifact is unreadable; this round reviews without it",
            metadata={
                "stepId": step.id,
                "stage": step.stage.lower(),
                "round": self._round_number(run, step),
                "reason": "previous review artifact is unreadable",
            },
        )

    def _decide(
        self,
        run: WorkflowExecution,
        decision: Literal["APPROVED", "REJECTED", "REQUEST_CHANGES"],
        comment: str,
    ) -> None:
        if run.approval_id is None:
            return
        service, _ = self._engine._approval_dependencies()
        service.decide(
            ApprovalDecision(
                approval_id=run.approval_id,
                reviewer=AI_REVIEWER,
                reviewer_kind="AI",
                decision=decision,
                comment=comment,
                created_at=self._engine._now(),
            )
        )

    def _escalate(
        self, run: WorkflowExecution, step: WorkflowStepDef, escalation: Escalation
    ) -> None:
        """Force the gate to its ESCALATED stage with an audit reason.

        The decision is recorded as REQUEST_CHANGES (its comment
        becomes the producer's feedback after an operator resume);
        the revision counter is then set to the graph's limit so the
        state machine's own REVISE guard takes the escalation edge.
        """
        engine = self._engine
        self._decide(run, "REQUEST_CHANGES", escalation.comment or escalation.reason)
        graph_max = engine._graph.max_revisions.get(step.id, 0)
        run.state = RunState(
            stage=run.state.stage,
            revisions={**run.state.revisions, step.id: graph_max},
        )
        engine._sync_approval(run)
        metadata: dict[str, str] = {"stepId": step.id, "reason": escalation.reason}
        if escalation.error_code is not None:
            metadata["errorCode"] = escalation.error_code
        if escalation.error_message is not None:
            metadata["errorMessage"] = escalation.error_message
        if escalation.provider_message is not None:
            metadata["providerMessage"] = escalation.provider_message
        engine._event(
            run,
            "WORKFLOW_ESCALATED",
            f"AI review of {step.name} escalated: {escalation.reason}",
            metadata=metadata,
        )

    def _failed_result(
        self, request_id: str, agent_id: str, code: str, message: str
    ) -> AgentResult:
        error = PlatformError(
            code=code,
            message=message,
            category="AGENT",
            retryable=False,
            timestamp=self._engine._now(),
        )
        return AgentResult(
            request_id=request_id,
            agent_id=agent_id,
            status="FAILED",
            errors=[error],
            metrics=RunMetrics(duration_seconds=0, revision_count=0, attempt=1),
        )
