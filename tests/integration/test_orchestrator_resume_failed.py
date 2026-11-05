"""Resume-from-failure: a FAILED run forks into a new run at its failed step."""

from __future__ import annotations

import pytest

from asf.contracts.models import AgentResult, RunMetrics
from tests.integration.test_orchestrator_rework import drive, harness, review


def _explode(request):
    raise RuntimeError("model gateway unreachable")


def test_failure_at_test_step_resumes_without_reapproval_or_rewrite(
    tmp_path,
    monkeypatch,
):
    engine, run, store, gateways, _, sandbox = harness(
        tmp_path,
        review_replies=[review()],
        exits=[0],
    )
    tester = engine._registry.for_type("test")
    monkeypatch.setattr(tester, "execute", _explode)
    run = drive(engine, run)
    assert run.state.stage == "FAILED"
    assert run.errors[0].code == "AGENT_EXECUTION_FAILED"
    assert set(run.artifacts) >= {"SPEC", "PLAN", "TASK", "CODE", "CODE_REVIEW"}
    approvals_before = store.approvals.list_by_task("work-1")
    assert len(approvals_before) == 3
    monkeypatch.undo()

    resumed = engine.resume_failed(run.id)
    assert resumed.id != run.id
    assert resumed.task_id == run.task_id
    assert resumed.state.stage == "TESTING"
    assert resumed.approval_id is None
    assert set(resumed.artifacts) == set(run.artifacts)
    assert set(resumed.artifact_history) == set(run.artifact_history)
    assert any(run.id in note for note in resumed.recovery_notes)
    # The failed run stays untouched as the record of the failure.
    assert engine.get(run.id).state.stage == "FAILED"

    resumed = drive(engine, resumed)
    assert resumed.state.stage == "COMPLETED", [
        (error.code, error.message) for error in resumed.errors
    ]
    # Nothing upstream of the failed step ran again: no new model calls for
    # spec/plan/task/implement/review and no new approval requests.
    assert len(gateways["spec"].requests) == 1
    assert len(gateways["plan"].requests) == 1
    assert len(gateways["task"].requests) == 1
    assert len(gateways["implement"].requests) == 1
    assert len(store.approvals.list_by_task("work-1")) == 3
    assert len(sandbox.calls) == 1
    store.close()


def test_failure_at_first_step_resumes_from_the_spec(tmp_path, monkeypatch):
    engine, run, store, gateways, _, _ = harness(
        tmp_path,
        review_replies=[review()],
        exits=[0],
    )
    spec_agent = engine._registry.for_type("spec")
    monkeypatch.setattr(spec_agent, "execute", _explode)
    run = drive(engine, run)
    assert run.state.stage == "FAILED"
    assert run.artifacts == {}
    monkeypatch.undo()

    resumed = engine.resume_failed(run.id)
    assert resumed.state.stage == "SPEC_DRAFT"
    resumed = drive(engine, resumed)
    assert resumed.state.stage == "COMPLETED"
    assert len(gateways["spec"].requests) == 1
    store.close()


def test_missing_ci_handler_failure_resumes_into_injected_handlers(tmp_path):
    engine, run, store, _, _, _ = harness(
        tmp_path,
        review_replies=[review()],
        exits=[0],
        with_actions=True,
    )
    run = drive(engine, run)
    assert run.state.stage == "FAILED"
    assert run.errors[0].code == "INTEGRATION_UNAVAILABLE"
    assert list(run.item_results) == ["T1"]

    resumed = engine.resume_failed(run.id)
    assert resumed.state.stage == "CI"
    received = []

    def handler(request):
        received.append(request)
        return AgentResult(
            request_id=request.request_id,
            agent_id=request.agent_id,
            status="SUCCESS",
            output={"summary": "simulated action"},
            metrics=RunMetrics(duration_seconds=0, revision_count=0, attempt=1),
        )

    engine._actions = {"run-pipeline": handler, "await-merge": handler}
    resumed = drive(engine, resumed)
    assert resumed.state.stage == "COMPLETED"
    assert [request.agent_id for request in received] == [
        "action:run-pipeline",
        "action:await-merge",
    ]
    store.close()


def test_resume_failed_rejects_runs_that_have_not_failed(tmp_path):
    engine, run, store, _, _, _ = harness(
        tmp_path,
        review_replies=[review()],
        exits=[0],
    )
    with pytest.raises(ValueError, match="has not failed"):
        engine.resume_failed(run.id)
    with pytest.raises(KeyError):
        engine.resume_failed("no-such-run")
    run = drive(engine, run)
    assert run.state.stage == "COMPLETED"
    with pytest.raises(ValueError, match="has not failed"):
        engine.resume_failed(run.id)
    store.close()
