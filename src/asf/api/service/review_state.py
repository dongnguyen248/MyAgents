"""Approval-gate state helpers shared by the service mixins.

Pure functions over a run and its current step: the queries mixin
uses them to label a run's status, the driver mixin to decide
whether a run is parked for a person. They live outside the mixins
so neither class grows with Phase 12's mode resolution.
"""

from __future__ import annotations

from typing import Any

from asf.approval.mode import approval_overrides_from_context, resolve_approval_mode
from asf.orchestrator.execution import WorkflowExecution
from asf.workflow.definition import WorkflowStepDef

__all__ = [
    "ai_review_waiting",
    "approval_mode_of",
    "approval_view_fields",
    "escalation_detail",
    "escalation_waiting",
    "is_human_wait",
    "project_approval_fields",
    "review_status",
]

_APPROVAL_VIEW_KEYS = (
    "approvalChannel",
    "approvalMode",
    "approvalMaxRevisions",
    "approvalOnExhausted",
)


def project_approval_fields(profile: Any) -> dict[str, Any]:
    """The approval fields of a normalized project profile, for list views."""
    return {key: profile[key] for key in _APPROVAL_VIEW_KEYS}


_OPEN_STATUSES = ("NEW", "STILL_OPEN")


def approval_mode_of(run: WorkflowExecution, step: WorkflowStepDef | None) -> str | None:
    """The resolved approval mode of the run's current gated step."""
    if step is None:
        return None
    overrides = approval_overrides_from_context(run.context)
    return resolve_approval_mode(step, overrides).mode


def review_status(run: WorkflowExecution, step: WorkflowStepDef | None) -> str:
    """The workflow status of a run parked at an approval gate."""
    return "AI_REVIEWING" if approval_mode_of(run, step) == "ai" else "WAITING_APPROVAL"


def approval_view_fields(
    run: WorkflowExecution, request: Any, step: WorkflowStepDef | None
) -> dict[str, Any]:
    """The Phase 12 fields of an approval view: run link, addressees, mode.

    The dashboard groups pending approvals by these fields:
    human-mode gates need a person; ai-mode gates are listed for
    oversight (a human may still override them).
    """
    fields: dict[str, Any] = {
        "workflowId": run.id,
        "reviewers": list(request.reviewers),
    }
    mode = approval_mode_of(run, step)
    if mode is not None:
        fields["mode"] = mode
    return fields


def ai_review_waiting(
    run: WorkflowExecution, step: WorkflowStepDef | None, waiting: dict[str, Any]
) -> dict[str, Any]:
    """Fill the waiting block for a run inside the AI review loop."""
    waiting["kind"] = "AI_REVIEW"
    waiting["suggestedActions"] = ["approve", "reject", "cancel"]
    if step is None:
        waiting["reason"] = "AI review in progress"
        return waiting
    resolved = resolve_approval_mode(step, approval_overrides_from_context(run.context))
    current = run.state.revisions.get(step.id, 0) + 1
    step_cap = step.max_revisions
    cap = resolved.max_revisions if step_cap is None else min(resolved.max_revisions, step_cap)
    waiting["stage"] = step.stage
    waiting["round"] = current
    waiting["maxRounds"] = cap
    waiting["reason"] = f"AI review of {step.name} in progress (round {current} of {cap})"
    for obs in reversed(run.observations):
        event = obs.event
        if event is None or event.event_type != "AI_REVIEW_STARTED":
            continue
        if event.metadata.get("stepId") == step.id:
            waiting["since"] = event.timestamp.isoformat()
            break
    return waiting


def _escalation_reason(run: WorkflowExecution) -> str | None:
    for obs in reversed(run.observations):
        event = obs.event
        if event is not None and event.event_type == "WORKFLOW_ESCALATED":
            raw = event.metadata.get("reason")
            return raw if isinstance(raw, str) else None
    return None


def _latest_review(run: WorkflowExecution, stage: str) -> Any:
    latest: Any = None
    for artifact in run.artifact_history.values():
        if artifact.type != "ARTIFACT_REVIEW":
            continue
        if artifact.metadata.get("stage") != stage:
            continue
        if latest is None or artifact.metadata.get("round", 0) > latest.metadata.get("round", 0):
            latest = artifact
    return latest


def _open_blockers(review_artifact: Any) -> int:
    if review_artifact is None:
        return 0
    content = review_artifact.content
    review = content.get("review") if isinstance(content, dict) else None
    findings = review.get("findings") if isinstance(review, dict) else None
    if not isinstance(findings, list):
        return 0
    return sum(
        1
        for finding in findings
        if isinstance(finding, dict)
        and finding.get("severity") == "BLOCKER"
        and finding.get("status") in _OPEN_STATUSES
    )


def escalation_detail(
    run: WorkflowExecution, step: WorkflowStepDef | None
) -> tuple[str | None, int]:
    """The escalation reason and open blocker count for an escalated run.

    The reason rides on the WORKFLOW_ESCALATED event (AI review
    escalations carry MAX_REVISIONS / NO_PROGRESS / REVIEWER_FAILED
    / BUDGET); the blocker count comes from the latest review
    artifact of the escalated step, counting findings that are
    still open at BLOCKER severity.
    """
    reason = _escalation_reason(run)
    if step is None:
        return reason, 0
    latest = _latest_review(run, step.stage.lower())
    return reason, _open_blockers(latest)


def escalation_waiting(
    run: WorkflowExecution,
    step: WorkflowStepDef | None,
    waiting: dict[str, Any],
    budget: dict[str, int],
) -> dict[str, Any]:
    """Fill the waiting block for an escalated run."""
    waiting["kind"] = "ESCALATED"
    waiting["budget"] = budget
    waiting["suggestedActions"] = ["resume", "cancel"]
    waiting["reason"] = (
        f"Escalated — fix budget used ({budget['used']}/{budget['max']}), needs operator"
    )
    escalated = next(
        (
            obs.event
            for obs in reversed(run.observations)
            if obs.event is not None and obs.event.event_type == "WORKFLOW_ESCALATED"
        ),
        None,
    )
    if escalated is not None:
        waiting["since"] = escalated.timestamp.isoformat()
        waiting["reason"] = escalated.message
    reason, open_blockers = escalation_detail(run, step)
    waiting["escalationReason"] = reason
    waiting["openBlockers"] = open_blockers
    if step is not None and step.requires_approval:
        waiting["suggestedActions"] = ["resume", "approve", "cancel"]
    return waiting


def is_human_wait(run: WorkflowExecution, step: WorkflowStepDef | None) -> bool:
    """Parked for a person: at an approval gate a human must decide.

    AI-mode review stages are not human waits (the review loop
    decides), and neither are escalations or retry backoffs —
    those have their own owners (operator, scheduler).
    """
    return (
        step is not None
        and step.requires_approval
        and run.state.stage == f"{step.stage}_REVIEW"
        and approval_mode_of(run, step) != "ai"
    )
