"""Stage E view helpers: approval view fields + project approval fields."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from asf.api.service.approval_context import approval_settings_view
from asf.api.service.review_state import (
    approval_view_fields,
    escalation_waiting,
    project_approval_fields,
)
from asf.contracts.models import ActivityEvent
from asf.orchestrator.execution import Observation, RunState, WorkflowExecution
from asf.workflow.definition import WorkflowStepDef

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _run(context: dict) -> WorkflowExecution:
    return WorkflowExecution(
        id="run-1",
        task_id="task-1",
        project_id="proj",
        state=RunState(stage="SPEC_REVIEW"),
        context=context,
        started_at=NOW,
        updated_at=NOW,
    )


def _step() -> WorkflowStepDef:
    return WorkflowStepDef.model_validate(
        {
            "id": "spec",
            "name": "Write spec",
            "type": "AGENT",
            "stage": "SPEC",
            "agentType": "spec",
            "requiresApproval": True,
            "approval": {"mode": "ai", "maxRevisions": 4},
            "produces": ["SPEC"],
        }
    )


def test_approval_view_fields_carry_run_reviewers_and_mode() -> None:
    request = SimpleNamespace(reviewers=["ai-reviewer", "dashboard"])
    fields = approval_view_fields(_run({}), request, _step())
    assert fields == {
        "workflowId": "run-1",
        "reviewers": ["ai-reviewer", "dashboard"],
        "mode": "ai",
    }


def test_approval_view_fields_without_a_step_omit_mode() -> None:
    request = SimpleNamespace(reviewers=["dashboard"])
    fields = approval_view_fields(_run({}), request, None)
    assert fields == {"workflowId": "run-1", "reviewers": ["dashboard"]}


def test_approval_settings_view_reads_camel_and_snake_case() -> None:
    view = approval_settings_view(
        {"channel": "teams", "mode": "ai", "maxRevisions": 5, "onExhausted": "escalate"}
    )
    assert view == {
        "approvalChannel": "teams",
        "approvalMode": "ai",
        "approvalMaxRevisions": 5,
        "approvalOnExhausted": "escalate",
    }
    snake = approval_settings_view({"max_revisions": 3, "on_exhausted": "accept_with_warnings"})
    assert snake["approvalMaxRevisions"] == 3
    assert snake["approvalOnExhausted"] == "accept_with_warnings"


def test_approval_settings_view_degrades_safely() -> None:
    empty = {
        "approvalChannel": "",
        "approvalMode": "",
        "approvalMaxRevisions": None,
        "approvalOnExhausted": "",
    }
    assert approval_settings_view(None) == empty
    assert approval_settings_view({"maxRevisions": True}) == empty
    assert approval_settings_view({"maxRevisions": "5"}) == empty


def test_project_approval_fields_copy_the_four_keys() -> None:
    profile = {
        "approvalChannel": "teams",
        "approvalMode": "human",
        "approvalMaxRevisions": 2,
        "approvalOnExhausted": "",
        "other": "ignored",
    }
    assert project_approval_fields(profile) == {
        "approvalChannel": "teams",
        "approvalMode": "human",
        "approvalMaxRevisions": 2,
        "approvalOnExhausted": "",
    }


def _escalated_run(metadata: dict) -> WorkflowExecution:
    run = _run({})
    run.state = RunState(stage="SPEC_ESCALATED")
    event = ActivityEvent(
        id="evt-1",
        timestamp=NOW,
        project_id="proj",
        event_type="WORKFLOW_ESCALATED",
        message="AI review of Write spec escalated: REVIEWER_FAILED",
        metadata=metadata,
    )
    run.observations.append(Observation(id="obs-1", event=event))
    return run


def test_escalation_waiting_carries_the_reviewer_cause() -> None:
    run = _escalated_run(
        {
            "stepId": "spec",
            "reason": "REVIEWER_FAILED",
            "errorCode": "LLM_MODEL_NOT_SUPPORTED",
            "errorMessage": "Model 'x' is not supported by the provider.",
        }
    )
    waiting = escalation_waiting(run, _step(), {}, {"used": 0, "max": 3})
    assert waiting["escalationReason"] == "REVIEWER_FAILED"
    assert waiting["errorCode"] == "LLM_MODEL_NOT_SUPPORTED"
    assert waiting["errorMessage"] == "Model 'x' is not supported by the provider."


def test_escalation_waiting_without_a_cause_keeps_the_old_shape() -> None:
    run = _escalated_run({"stepId": "spec", "reason": "MAX_REVISIONS"})
    waiting = escalation_waiting(run, _step(), {}, {"used": 1, "max": 3})
    assert waiting["escalationReason"] == "MAX_REVISIONS"
    assert "errorCode" not in waiting
    assert "errorMessage" not in waiting
