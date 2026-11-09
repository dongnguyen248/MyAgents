"""Escalated-gate operator actions for the commands mixin.

Kept outside ``commands.py`` so the mixin does not grow with the
Phase 12 approve-anyway / resume-guidance surface; the mixin
methods are thin delegates to these functions. Each function
takes the service (the commands mixin) as its first argument and
uses its engine, reviewer identity and drive hooks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from asf.orchestrator.code_loop import TEST_ESCALATED_STAGE
from asf.orchestrator.execution import WorkflowExecution
from asf.orchestrator.gate_ops import approve_anyway, deliver_guidance
from asf.orchestrator.test_ops import TestCommandReplacement, replace_test_commands, skip_tests

__all__ = [
    "EscalationResume",
    "approve_escalated_run",
    "escalated_agent_id",
    "replace_test_commands_run",
    "resume_escalated_run",
    "skip_tests_run",
]


@dataclass(frozen=True)
class EscalationResume:
    """A resume request for an escalated run."""

    run_id: str
    reason: str
    operator: str = "operator"
    guidance: str | None = None


def escalated_agent_id(service: Any, run: WorkflowExecution) -> str | None:
    """The agent that produced the escalated step's artifact."""
    step = service._step_for_stage(run, run.state.stage)
    if step is None or not step.produces:
        return None
    artifact = run.artifacts.get(step.produces[0])
    return artifact.created_by if artifact is not None else None


def _require_escalated(service: Any, run: WorkflowExecution, run_id: str, action: str) -> None:
    if service._stage_kind(run, run.state.stage) != "ESCALATED":
        raise ValueError(
            f"Run '{run_id}' is not escalated (stage {run.state.stage}); "
            f"only an escalated run can be {action}"
        )


def _require_test_stop(service: Any, run: WorkflowExecution, run_id: str, action: str) -> None:
    if run.state.stage != TEST_ESCALATED_STAGE:
        raise ValueError(
            f"Run '{run_id}' is at {run.state.stage}, not {TEST_ESCALATED_STAGE}; "
            f"only a run stopped for a NO_TESTS decision can {action}"
        )


def skip_tests_run(
    service: Any, run_id: str, *, reason: str, operator: str = "operator"
) -> dict[str, Any] | None:
    """Skip a NO_TESTS run's test step (reason mandatory) and drive on."""
    run = service._operator_target(run_id)
    _require_test_stop(service, run, run_id, "skip its tests")
    view = service._operator_call(
        "test skip",
        lambda: skip_tests(service._engine, run_id, reason=reason, operator=operator),
    )
    service._drive_in_background(run_id)
    return view


def replace_test_commands_run(
    service: Any, request: TestCommandReplacement
) -> dict[str, Any] | None:
    """Replace a NO_TESTS run's test commands (run-scoped) and retest."""
    run = service._operator_target(request.run_id)
    _require_test_stop(service, run, request.run_id, "replace its test commands")
    view = service._operator_call(
        "test commands replace",
        lambda: replace_test_commands(service._engine, request),
    )
    service._drive_in_background(request.run_id)
    return view


def resume_escalated_run(service: Any, request: EscalationResume) -> dict[str, Any] | None:
    """Grant an escalated run a fresh fix budget and drive it on.

    Only a run whose stage kind is ESCALATED qualifies — the
    engine enforces the same rule; the service check exists to
    answer with a clear operator-facing message. Optional
    guidance is delivered to the producer as feedback (a human
    REQUEST_CHANGES decision) on its next dispatch.
    """
    run_id = request.run_id
    run = service._operator_target(run_id)
    _require_escalated(service, run, run_id, "resumed with a new fix budget")
    agent_id = escalated_agent_id(service, run)
    view = service._operator_call(
        "escalation resume",
        lambda: service._engine.resume(run_id, reason=request.reason, operator=request.operator),
    )
    guidance = request.guidance
    if guidance and guidance.strip():
        deliver_guidance(
            service._engine, run_id, guidance=guidance.strip(), operator=request.operator
        )
        service._record_approval_decision(run, agent_id, "REQUEST_CHANGES")
    service._drive_in_background(run_id)
    return view


def approve_escalated_run(
    service: Any, run_id: str, *, reason: str, operator: str = "operator"
) -> dict[str, Any] | None:
    """Approve an escalated gate's artifact anyway and drive on.

    The decision is recorded on a fresh approval request as
    the service reviewer (kind HUMAN); the reason is its
    comment. Only an escalated approval gate qualifies.
    """
    run = service._operator_target(run_id)
    _require_escalated(service, run, run_id, "approved anyway")
    step = service._step_for_stage(run, run.state.stage)
    if step is None or not step.requires_approval:
        raise ValueError(
            f"Run '{run_id}' escalated at {run.state.stage}, which is not "
            "an approval gate; approve-anyway does not apply"
        )
    agent_id = escalated_agent_id(service, run)
    view = service._operator_call(
        "escalation approve",
        lambda: approve_anyway(service._engine, run_id, reviewer=service._reviewer, comment=reason),
    )
    service._record_approval_decision(run, agent_id, "APPROVED")
    service._drive_in_background(run_id)
    return view
