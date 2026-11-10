"""Waiting-block shape at a no-tests stop and at other escalations.

At TEST_ESCALATED the operator decides about the test commands, so
the waiting block offers exactly skip_tests / replace_test_commands
/ cancel, hides the fix budget, and carries the run's baked test
commands with secrets redacted. Fix-loop and approval-gate
escalations keep their previous actions byte-for-byte.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from asf.api.service.review_state import escalation_waiting
from asf.contracts.models import ActivityEvent
from asf.orchestrator.execution import Observation, WorkflowExecution
from asf.state_machine.machine import RunState
from asf.workflow.definition import WorkflowStepDef

NOW = datetime(2026, 11, 9, tzinfo=UTC)
BUDGET = {"used": 2, "max": 3}
ESCALATED_MESSAGE = "No tests were collected by 'pytest -q' (pytest exit 5)"


def _run(
    stage: str,
    *,
    context: dict[str, Any] | None = None,
    escalated: bool = False,
) -> WorkflowExecution:
    observations: list[Observation] = []
    if escalated:
        observations.append(
            Observation(
                id="obs-1",
                event=ActivityEvent(
                    id="obs-1",
                    timestamp=NOW,
                    project_id="proj-1",
                    task_id="task-1",
                    workflow_id="wf",
                    event_type="WORKFLOW_ESCALATED",
                    message=ESCALATED_MESSAGE,
                    metadata={"reason": "NO_TESTS"},
                ),
            )
        )
    return WorkflowExecution(
        id="run-1",
        task_id="task-1",
        project_id="proj-1",
        state=RunState(stage=stage, revisions={}),
        context=context or {},
        definition={"id": "wf"},
        started_at=NOW,
        updated_at=NOW,
        observations=observations,
    )


def _waiting() -> dict[str, Any]:
    return {
        "kind": "NONE",
        "since": NOW.isoformat(),
        "reason": None,
        "retryAt": None,
        "budget": None,
        "suggestedActions": [],
    }


def test_test_stop_offers_test_actions_hides_budget_and_redacts_commands() -> None:
    run = _run(
        "TEST_ESCALATED",
        context={
            "project": {
                "testCommands": [
                    ["python", "-m", "pytest", "-q"],
                    ["deploy", "Bearer abcdefghijklmnopqrstuv"],
                ]
            }
        },
        escalated=True,
    )
    waiting = escalation_waiting(run, None, _waiting(), dict(BUDGET))
    assert waiting["suggestedActions"] == [
        "skip_tests",
        "replace_test_commands",
        "cancel",
    ]
    assert waiting["budget"] is None
    assert waiting["testCommands"] == [
        ["python", "-m", "pytest", "-q"],
        ["deploy", "[REDACTED]"],
    ]
    assert waiting["reason"] == ESCALATED_MESSAGE
    assert waiting["escalationReason"] == "NO_TESTS"


def test_test_stop_without_baked_commands_exposes_an_empty_list() -> None:
    run = _run("TEST_ESCALATED", escalated=True)
    waiting = escalation_waiting(run, None, _waiting(), dict(BUDGET))
    assert waiting["testCommands"] == []
    assert waiting["suggestedActions"] == [
        "skip_tests",
        "replace_test_commands",
        "cancel",
    ]


def test_code_fix_escalation_keeps_resume_and_budget() -> None:
    run = _run("CODE_FIX_ESCALATED")
    waiting = escalation_waiting(run, None, _waiting(), dict(BUDGET))
    assert waiting["suggestedActions"] == ["resume", "cancel"]
    assert waiting["budget"] == BUDGET
    assert "testCommands" not in waiting


def test_gate_escalation_keeps_approve() -> None:
    step = WorkflowStepDef(
        id="spec",
        name="Write specification",
        type="agent",
        stage="SPEC",
        requires_approval=True,
        agent_type="spec",
    )
    run = _run("SPEC_ESCALATED")
    waiting = escalation_waiting(run, step, _waiting(), dict(BUDGET))
    assert waiting["suggestedActions"] == ["resume", "approve", "cancel"]
    assert waiting["budget"] == BUDGET
    assert "testCommands" not in waiting
