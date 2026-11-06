"""Operator operations on escalated approval gates.

Two actions the plain state machine cannot express on its own,
kept out of ``engine.py`` (which delegates to this module):

- ``approve_anyway``: an operator accepts an escalated gate's
  artifact as-is. The decision is auditable — a fresh approval
  request is created for the artifact and decided APPROVED by
  the operator (reviewer kind HUMAN) — and the run then moves
  along the graph's ESCALATED --APPROVED--> APPROVED --ADVANCE-->
  edges like a normal approval.
- ``deliver_guidance``: an operator's guidance comment, given
  with a resume, is stored as the run's pending feedback so the
  producer's next dispatch receives it exactly like rejection
  feedback (a human REQUEST_CHANGES decision).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from asf.approval.mode import approval_policy_from_context
from asf.approval.models import (
    ApprovalDecision,
    ApprovalFeedback,
    ApprovalPolicy,
    ApprovalSpec,
)
from asf.approval.service import ApprovalService
from asf.contracts.models import Artifact
from asf.state_machine.machine import InvalidTransition, apply
from asf.state_machine.status import kind_of
from asf.state_machine.triggers import StageKind, Trigger
from asf.workflow.definition import WorkflowStepDef

if TYPE_CHECKING:
    from asf.orchestrator.engine import Orchestrator
    from asf.orchestrator.execution import WorkflowExecution

logger = logging.getLogger(__name__)

__all__ = ["approve_anyway", "deliver_guidance"]

_DEFAULT_OVERRIDE_COMMENT = "Approved by the operator despite escalation."


@dataclass(frozen=True)
class _Override:
    engine: Orchestrator
    run: WorkflowExecution
    step: WorkflowStepDef
    artifact: Artifact
    reviewer: str
    comment: str


def _escalated_gate(
    engine: Orchestrator, run: WorkflowExecution
) -> tuple[WorkflowStepDef, Artifact]:
    if kind_of(engine._graph, run.state.stage) != StageKind.ESCALATED:
        raise InvalidTransition(run.state.stage, Trigger.APPROVED.value)
    step = engine._step(run)
    artifact = run.artifacts.get(step.produces[0]) if step.produces else None
    if not step.requires_approval or artifact is None:
        raise ValueError(
            f"Stage {run.state.stage} is not an approval gate with an artifact; "
            "approve-anyway does not apply"
        )
    return step, artifact


def _record_override(ctx: _Override, service: ApprovalService, policy: ApprovalPolicy) -> None:
    spec = ApprovalSpec(
        task_id=ctx.run.task_id,
        project_id=ctx.run.project_id,
        workflow_id=ctx.engine._definition.id,
        artifact_id=ctx.artifact.id,
        type=ctx.step.produces[0],
        requested_by="operator",
        metadata={"runId": ctx.run.id, "stepId": ctx.step.id},
    )
    request = service.request(spec, policy, ctx.engine._now())
    service.decide(
        ApprovalDecision(
            approval_id=request.id,
            reviewer=ctx.reviewer,
            reviewer_kind="HUMAN",
            decision="APPROVED",
            comment=ctx.comment,
            created_at=ctx.engine._now(),
        )
    )


def _advance_override(ctx: _Override) -> None:
    ctx.run.state = apply(ctx.engine._graph, ctx.run.state, Trigger.APPROVED)
    ctx.run.state = apply(ctx.engine._graph, ctx.run.state, Trigger.ADVANCE)
    ctx.run.recovery_notes.append(ctx.comment)
    ctx.engine._event(
        ctx.run,
        "APPROVAL_APPROVED_ANYWAY",
        f"Operator approved {ctx.step.name} despite escalation",
        metadata={"stepId": ctx.step.id, "reviewer": ctx.reviewer},
    )


def approve_anyway(
    engine: Orchestrator, run_id: str, *, reviewer: str, comment: str
) -> WorkflowExecution:
    """Approve an escalated gate's artifact and advance the run."""
    service, base_policy = engine._approval_dependencies()
    with engine._edit(run_id) as run:
        step, artifact = _escalated_gate(engine, run)
        ctx = _Override(
            engine=engine,
            run=run,
            step=step,
            artifact=artifact,
            reviewer=reviewer,
            comment=comment.strip() or _DEFAULT_OVERRIDE_COMMENT,
        )
        policy = approval_policy_from_context(run.context) or base_policy
        _record_override(ctx, service, policy)
        _advance_override(ctx)
    return engine.get(run_id)


def deliver_guidance(
    engine: Orchestrator, run_id: str, *, guidance: str, operator: str
) -> WorkflowExecution:
    """Store operator guidance as the feedback for the next dispatch."""
    service, _ = engine._approval_dependencies()
    with engine._edit(run_id) as run:
        request_id = run.id
        try:
            requests = service._repository.list_by_task(run.task_id)
        except Exception:
            logger.warning("guidance feedback could not resolve the last request", exc_info=True)
            requests = []
        if requests:
            request_id = max(requests, key=lambda item: item.requested_at).id
        run.feedback = [
            ApprovalFeedback(
                approval_id=request_id,
                reviewer=operator,
                decision="REQUEST_CHANGES",
                comment=guidance,
            )
        ]
    return engine.get(run_id)
