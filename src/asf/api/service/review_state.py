"""Approval-gate state helpers shared by the service mixins.

Pure functions over a run and its current step: the queries mixin
uses them to label a run's status, the driver mixin to decide
whether a run is parked for a person. They live outside the mixins
so neither class grows with Phase 12's mode resolution.
"""

from __future__ import annotations

from asf.approval.mode import approval_overrides_from_context, resolve_approval_mode
from asf.orchestrator.execution import WorkflowExecution
from asf.workflow.definition import WorkflowStepDef

__all__ = ["approval_mode_of", "is_human_wait", "review_status"]


def approval_mode_of(run: WorkflowExecution, step: WorkflowStepDef | None) -> str | None:
    """The resolved approval mode of the run's current gated step."""
    if step is None:
        return None
    overrides = approval_overrides_from_context(run.context)
    return resolve_approval_mode(step, overrides).mode


def review_status(run: WorkflowExecution, step: WorkflowStepDef | None) -> str:
    """The workflow status of a run parked at an approval gate."""
    return "AI_REVIEWING" if approval_mode_of(run, step) == "ai" else "WAITING_APPROVAL"


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
