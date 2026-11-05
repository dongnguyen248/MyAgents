from __future__ import annotations

import sqlite3
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from asf.agents.base import AgentExecutionError
from asf.approval.errors import ApprovalError
from asf.approval.models import ApprovalPolicy
from asf.configuration.platform import RetryPolicySettings
from asf.models.errors import ModelGatewayError
from asf.orchestrator import Orchestrator
from asf.state_machine.machine import InvalidTransition
from asf.storage.sqlite import SQLiteExecutionStore
from tests.unit.contract_models import validator_for
from tests.unit.test_orchestrator import NOW, make_engine, start


def durable_engine(tmp_path, *, approval=True):
    original, spec, plan, _ = make_engine(approval=approval)
    store = SQLiteExecutionStore(tmp_path / "workflow.sqlite")
    engine = Orchestrator(
        original._definition, original._registry,
        clock=original._clock, new_id=original._new_id, store=store,
        approval_policy=ApprovalPolicy(reviewers=["one", "two"], min_approvals=2),
    )
    return engine, spec, plan, store


def reopen(engine, store, tmp_path):
    store.close()
    store = SQLiteExecutionStore(tmp_path / "workflow.sqlite")
    return Orchestrator(
        engine._definition, engine._registry, clock=engine._clock,
        new_id=engine._new_id, store=store, approval_policy=engine._approval_policy,
        code_loop=engine._code_loop,
    ), store


def test_restart_preserves_partial_quorum_and_does_not_repeat_agent(tmp_path):
    engine, spec, plan, store = durable_engine(tmp_path)
    run = engine.tick(start(engine).id)
    run = engine.decide(run.id, reviewer="one", decision="APPROVED")
    approval_id = run.approval_id
    assert len(run.results) == 1
    engine, store = reopen(engine, store, tmp_path)
    assert engine.get(run.id).state.stage == "SPEC_REVIEW"
    assert len(store.approvals.list_decisions(approval_id)) == 1
    assert engine.tick(run.id).state.stage == "SPEC_REVIEW"
    assert len(engine.get(run.id).results) == 1
    run = engine.decide(run.id, reviewer="two", decision="APPROVED")
    assert run.state.stage == "PLAN"
    assert len(store.approvals.list_decisions(approval_id)) == 2
    run = engine.tick(run.id)
    assert run.state.stage == "COMPLETED"
    assert spec.run_called and plan.run_called
    assert len(run.results) == 2
    assert len(run.artifact_history) == 2
    validator_for("WorkflowRun").validate(engine.workflow_run(run.id))
    validator_for("Task").validate(engine.task(run.id))
    assert engine.workflow_run(run.id)["stage"] == engine.task(run.id)["stage"]
    store.close()


def test_decision_and_execution_checkpoint_roll_back_together(tmp_path, monkeypatch):
    engine, _, _, store = durable_engine(tmp_path)
    run = engine.tick(start(engine).id)
    approval_id = run.approval_id
    save = store.save_execution

    def broken(run):
        raise sqlite3.OperationalError("simulated storage failure")

    monkeypatch.setattr(store, "save_execution", broken)
    with pytest.raises(sqlite3.OperationalError):
        engine.decide(run.id, reviewer="one", decision="APPROVED")
    assert store.approvals.list_decisions(approval_id) == []
    assert store.approvals.get(approval_id).status == "PENDING"
    assert engine.get(run.id).state.stage == "SPEC_REVIEW"
    monkeypatch.setattr(store, "save_execution", save)
    engine.decide(run.id, reviewer="one", decision="APPROVED")
    assert len(store.approvals.list_decisions(approval_id)) == 1
    store.close()


def test_result_and_new_approval_roll_back_but_inflight_checkpoint_survives(tmp_path, monkeypatch):
    engine, spec, _, store = durable_engine(tmp_path)
    run = start(engine)
    save = store.save_execution

    def broken(run):
        if run.results:
            raise sqlite3.OperationalError("simulated storage failure")
        save(run)

    monkeypatch.setattr(store, "save_execution", broken)
    with pytest.raises(sqlite3.OperationalError):
        engine.tick(run.id)
    assert spec.run_called
    assert store.approvals.list_pending() == []
    saved = store.get_execution(run.id)
    assert saved.in_flight is not None
    assert saved.results == []
    assert saved.artifact_history == {}
    with pytest.raises(ValueError, match="recover"):
        engine.tick(run.id)
    store.close()


@pytest.mark.parametrize("retry_interrupted", [False, True])
def test_crash_recovery_never_replays_without_explicit_operator_acceptance(
    tmp_path, monkeypatch, retry_interrupted,
):
    engine, spec, _, store = durable_engine(tmp_path, approval=False)
    run = start(engine)
    execute = spec.execute

    def crash(request):
        raise SystemExit("simulated process exit")

    monkeypatch.setattr(spec, "execute", crash)
    with pytest.raises(SystemExit):
        engine.tick(run.id)
    engine, store = reopen(engine, store, tmp_path)
    assert engine.get(run.id).in_flight is not None
    with pytest.raises(ValueError):
        engine.tick(run.id)
    with pytest.raises(ValueError):
        engine.recover(run.id, reason=" ")
    with pytest.raises(ValueError):
        engine.cancel(run.id)
    run = engine.recover(
        run.id, reason="Operator reviewed interruption", retry_interrupted=retry_interrupted,
    )
    assert run.in_flight is None
    assert run.recovery_notes == ["Operator reviewed interruption"]
    monkeypatch.setattr(spec, "execute", execute)
    if retry_interrupted:
        assert run.state.stage == "SPEC"
        assert engine.tick(run.id).state.stage == "PLAN"
    else:
        assert run.state.stage == "FAILED"
        assert run.errors[0].code == "AGENT_EXECUTION_FAILED"
    store.close()


def test_restart_rejects_changed_definition_and_policy(tmp_path):
    engine, _, _, store = durable_engine(tmp_path)
    run = start(engine)
    changed = engine._definition.model_copy(update={"version": "2"})
    other = Orchestrator(
        changed, engine._registry, clock=engine._clock, new_id=engine._new_id,
        store=store, approval_policy=engine._approval_policy,
    )
    with pytest.raises(ValueError, match="differs"):
        other.get(run.id)
    other = Orchestrator(
        engine._definition, engine._registry, clock=engine._clock, new_id=engine._new_id,
        store=store, approval_policy=ApprovalPolicy(reviewers=["someone"]),
    )
    with pytest.raises(ValueError, match="differs"):
        other.tick(run.id)
    store.close()


def test_persistent_store_rejects_split_approval_repository(tmp_path):
    engine, _, _, store = durable_engine(tmp_path)
    with pytest.raises(ValueError, match="store"):
        Orchestrator(
            engine._definition, engine._registry, clock=engine._clock, new_id=engine._new_id,
            store=store, approvals=engine._approvals, approval_policy=engine._approval_policy,
        )
    store.close()


def test_store_missing_resources_duplicate_ids_and_project_filter(tmp_path):
    engine, _, _, store = durable_engine(tmp_path, approval=False)
    first = start(engine)
    engine.start(task_id="other-task", project_id="other-project")
    with pytest.raises(KeyError):
        store.get_execution("missing")
    with pytest.raises(KeyError):
        store.save_execution(first.model_copy(update={"id": "missing"}))
    with pytest.raises(sqlite3.IntegrityError):
        store.create_execution(first)
    assert [run.id for run in store.list_executions("project-1")] == [first.id]
    assert store.list_executions("unknown-project") == []
    snapshot = store.get_execution(first.id)
    snapshot.context["project"]["name"] = "modified"
    assert store.get_execution(first.id).context["project"]["name"] == "example"
    store.close()


def test_retry_schedule_respects_clock_allowlist_bounds_and_restart(tmp_path):
    original, spec, _, _ = make_engine(two_steps=False)
    definition = original._definition.model_copy(deep=True)
    definition.steps[0] = definition.steps[0].model_copy(update={
        "retry_policy": RetryPolicySettings(
            max_attempts=3, backoff_seconds=5, retry_on=["LLM_RATE_LIMITED"],
        ),
    })
    now = [NOW]
    store = SQLiteExecutionStore(tmp_path / "workflow.sqlite")
    engine = Orchestrator(
        definition, original._registry, clock=lambda: now[0], new_id=original._new_id,
        store=store,
    )
    spec._run_behavior = ModelGatewayError("LLM_RATE_LIMITED", "Rate limited")
    run = engine.tick(start(engine).id)
    assert run.state.stage == "SPEC"
    assert run.retry_at == NOW + timedelta(seconds=5)
    assert run.errors == []
    assert engine.workflow_run(run.id)["status"] == "WAITING"
    assert engine.task(run.id)["status"] == "WAITING"
    engine, store = reopen(engine, store, tmp_path)
    assert engine.tick(run.id).attempts["spec"] == 1
    now[0] += timedelta(seconds=5)
    run = engine.tick(run.id)
    assert run.retry_at == NOW + timedelta(seconds=15)
    assert run.attempts["spec"] == 2
    now[0] += timedelta(seconds=10)
    run = engine.tick(run.id)
    assert run.state.stage == "FAILED"
    assert run.attempts["spec"] == 3
    assert run.errors[0].code == "LLM_RATE_LIMITED"
    assert len(run.results) == 3
    assert sum(item.event.event_type == "WORKFLOW_RETRY_SCHEDULED"
               for item in run.observations if item.event) == 2
    store.close()


@pytest.mark.parametrize("retryable,allowlist", [
    (False, None), (True, ["LLM_TIMEOUT"]), (True, []),
])
def test_retry_never_overrides_nonretryable_or_unlisted_errors(retryable, allowlist):
    engine, spec, _, _ = make_engine(two_steps=False)
    engine._definition.steps[0] = engine._definition.steps[0].model_copy(update={
        "retry_policy": RetryPolicySettings(max_attempts=5, retry_on=allowlist),
    })
    spec._run_behavior = AgentExecutionError(
        "REPOSITORY_ERROR", "Safe failure", retryable=retryable,
    )
    run = engine.tick(start(engine).id)
    assert run.state.stage == "FAILED"
    assert run.attempts["spec"] == 1
    assert run.retry_at is None


def test_retry_success_resets_budget_and_retains_attempt_history():
    engine, spec, _, _ = make_engine(two_steps=False)
    engine._definition.steps[0] = engine._definition.steps[0].model_copy(update={
        "retry_policy": RetryPolicySettings(max_attempts=2),
    })
    original = spec._run_behavior
    spec._run_behavior = ModelGatewayError("LLM_TIMEOUT", "Timeout")
    run = engine.tick(start(engine).id)
    assert run.retry_at == NOW
    spec._run_behavior = original
    run = engine.tick(run.id)
    assert run.state.stage == "COMPLETED"
    assert run.retry_at is None and run.retry_attempts == 0
    assert run.attempts["spec"] == 2
    assert run.errors == []
    assert len(run.results) == 2


def test_backoff_wait_is_capped_and_cancellable():
    engine, spec, _, _ = make_engine(two_steps=False)
    engine._definition.steps[0] = engine._definition.steps[0].model_copy(update={
        "retry_policy": RetryPolicySettings(max_attempts=2, backoff_seconds=1_000_000),
    })
    spec._run_behavior = ModelGatewayError("LLM_TIMEOUT", "Timeout")
    run = engine.tick(start(engine).id)
    assert run.retry_at == NOW + timedelta(seconds=3600)
    run = engine.cancel(run.id)
    assert run.state.stage == "CANCELLED"
    assert run.retry_at is None


def test_approval_escalation_resume_reuses_feedback_and_resets_revision_budget():
    engine, spec, _, _ = make_engine(approval=True, revisions=0, two_steps=False)
    run = engine.tick(start(engine).id)
    run = engine.decide(run.id, reviewer="reviewer", decision="REJECTED", comment="More detail")
    assert run.state.stage == "SPEC_ESCALATED"
    with pytest.raises(ValueError):
        engine.resume(run.id, reason=" ")
    run = engine.resume(run.id, reason="Operator provided an additional revision window")
    assert run.state.stage == "SPEC_DRAFT"
    assert run.state.revisions["spec"] == 0
    run = engine.tick(run.id)
    assert spec.run_called and len(run.results) == 2
    assert run.state.stage == "SPEC_REVIEW"
    run = engine.decide(run.id, reviewer="reviewer", decision="APPROVED")
    assert run.state.stage == "COMPLETED"


def test_event_and_metrics_outbox_survives_failure_and_restart(tmp_path):
    engine, _, _, store = durable_engine(tmp_path, approval=False)
    run = engine.tick(start(engine).id)
    seen_events, seen_metrics = [], []

    class Events:
        def publish(self, event):
            seen_events.append(event.id)

    class Metrics:
        def record(self, agent_id, result, *, run_id=None):
            seen_metrics.append((agent_id, result.request_id))

    class Broken:
        def publish(self, event):
            raise RuntimeError("private delivery diagnostic")

    engine._events = Broken()
    with pytest.raises(RuntimeError, match="remains pending") as exc:
        engine.flush_observations(run.id)
    assert "private delivery diagnostic" not in repr(exc.value)
    assert not any(item.delivered for item in engine.get(run.id).observations)
    engine, store = reopen(engine, store, tmp_path)
    engine._events, engine._metrics = Events(), Metrics()
    run = engine.flush_observations(run.id)
    assert all(item.delivered for item in run.observations)
    assert len(seen_events) == len(set(seen_events))
    assert seen_metrics == [("agent-spec", run.results[0].request_id)]
    count_before = len(seen_events)
    engine.flush_observations(run.id)
    assert len(seen_events) == count_before and len(seen_metrics) == 1
    for item in run.observations:
        if item.event:
            validator_for("ActivityEvent").validate(item.event.to_contract())
    store.close()


def test_missing_sinks_leave_outbox_pending():
    engine, _, _, _ = make_engine(two_steps=False)
    run = engine.tick(start(engine).id)
    run = engine.flush_observations(run.id)
    assert run.observations
    assert not any(item.delivered for item in run.observations)


def test_action_handler_executes_through_contract_without_concrete_integration():
    engine, _, _, _ = make_engine(two_steps=False)
    engine._definition.steps[0] = engine._definition.steps[0].model_copy(update={
        "action": "test-action", "agent_type": None, "type": "SYSTEM", "produces": [],
    })
    from asf.contracts.models import AgentResult, RunMetrics

    received = []

    def action(request):
        received.append(request)
        return AgentResult(
            request_id=request.request_id, agent_id=request.agent_id, status="SUCCESS",
            output={"summary": "done"}, metrics=RunMetrics(
                duration_seconds=0, revision_count=0, attempt=1,
            ),
        )

    engine._actions["test-action"] = action
    run = engine.tick(start(engine).id)
    assert run.state.stage == "COMPLETED"
    assert received[0].agent_id == "action:test-action"
    assert len(run.results) == 1


def test_expired_decision_commits_expiry_and_failed_execution_atomically(tmp_path):
    engine, _, _, store = durable_engine(tmp_path)
    engine._approval_policy = ApprovalPolicy(reviewers=["one"], expires_in_seconds=1)
    run = engine.tick(start(engine).id)
    engine._clock = lambda: NOW + timedelta(seconds=2)
    with pytest.raises(ApprovalError) as exc:
        engine.decide(run.id, reviewer="one", decision="APPROVED")
    assert exc.value.code == "APPROVAL_EXPIRED"
    assert store.approvals.get(run.approval_id).status == "EXPIRED"
    assert store.approvals.list_decisions(run.approval_id) == []
    assert engine.get(run.id).state.stage == "FAILED"
    assert engine.get(run.id).errors[0].code == "APPROVAL_EXPIRED"
    store.close()


def test_observation_callback_cannot_recursively_dispatch_or_cancel():
    engine, _, _, _ = make_engine()
    run = engine.tick(start(engine).id)
    called = []

    class Events:
        def publish(self, event):
            with pytest.raises(ValueError):
                engine.tick(run.id)
            with pytest.raises(ValueError):
                engine.cancel(run.id)
            with pytest.raises(ValueError):
                engine.flush_observations(run.id)
            called.append(event.id)

    engine._events = Events()
    run = engine.flush_observations(run.id)
    assert called
    assert run.state.stage == "PLAN"
    assert len(run.results) == 1


def test_repeated_cancel_resume_and_recovery_of_noninterrupted_run_are_rejected():
    engine, _, _, _ = make_engine()
    run = start(engine)
    with pytest.raises(ValueError):
        engine.recover(run.id, reason="No interruption")
    with pytest.raises(InvalidTransition) as exc:
        engine.resume(run.id, reason="Not escalated")
    assert type(exc.value).__name__ == "InvalidTransition"
    run = engine.cancel(run.id)
    with pytest.raises(InvalidTransition) as exc:
        engine.cancel(run.id)
    assert type(exc.value).__name__ == "InvalidTransition"


def test_fresh_python_process_resumes_quorum_and_runs_plan_without_repeating_spec(tmp_path):
    engine, _, _, store = durable_engine(tmp_path)
    run = engine.tick(start(engine).id)
    engine.decide(run.id, reviewer="one", decision="APPROVED")
    store.close()
    script = r"""
import sys
from uuid import uuid4
from asf.agents.base import AgentRuntime
from asf.agents.plan import build_plan_agent
from asf.approval.models import ApprovalPolicy
from asf.models.fake import ScriptedModelGateway
from asf.orchestrator import AgentRegistry, Orchestrator
from asf.storage.sqlite import SQLiteExecutionStore
from asf.workflow.definition import WorkflowDefinition
from tests.integration.test_chain import PLATFORM, TEMPLATES_DIR, make_plan_artifact
from tests.unit.test_orchestrator import NOW

store = SQLiteExecutionStore(sys.argv[1])
saved = store.get_execution(sys.argv[2])
reply = make_plan_artifact().content["text"].replace(
    "ID: spec-1", "ID: " + saved.artifacts["SPEC"].id,
)
gateway = ScriptedModelGateway([reply])
registry = AgentRegistry()
registry.register(build_plan_agent(
    AgentRuntime(gateway, lambda: NOW, lambda: str(uuid4())), PLATFORM, TEMPLATES_DIR,
))
engine = Orchestrator(
    WorkflowDefinition.model_validate(saved.definition), registry,
    clock=lambda: NOW, new_id=lambda: str(uuid4()), store=store,
    approval_policy=ApprovalPolicy.model_validate(saved.settings["approvalPolicy"]),
)
run = engine.decide(saved.id, reviewer="two", decision="APPROVED")
run = engine.tick(run.id)
assert run.state.stage == "COMPLETED"
assert len(run.results) == 2
assert len(gateway.requests) == 1
assert run.results[0].agent_id == "agent-spec"
assert run.results[1].agent_id == "agent-plan"
store.close()
print("COMPLETED")
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path / "workflow.sqlite"), run.id],
        cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=30,
        check=False,
    )
    assert result.returncode == 0, "Fresh-process resume failed"
    assert result.stdout.strip() == "COMPLETED"
    store = SQLiteExecutionStore(tmp_path / "workflow.sqlite")
    assert store.get_execution(run.id).state.stage == "COMPLETED"
    assert len(store.get_execution(run.id).results) == 2
    store.close()
