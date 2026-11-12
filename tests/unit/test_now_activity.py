"""Now-card enrichment of currentActivity (single-run view only).

The enrichment derives who is acting, with which model, in which
phase, on which attempt, plus the run's recent events — entirely
from persisted state. List views must stay unenriched.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from asf.api.demo import build_demo
from asf.api.service.now_activity import enrich_activity
from asf.contracts.models import ActivityEvent
from asf.orchestrator.code_loop import FIX_STEP
from asf.orchestrator.execution import Observation, WorkflowExecution
from asf.state_machine.machine import RunState

NOW = datetime.now(UTC)
SHARED = "shared-model"
NEW_KEYS = {
    "agentId",
    "agentName",
    "model",
    "phase",
    "attempt",
    "attemptMax",
    "lastEventAt",
    "recentEvents",
}


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    service, engine, store = build_demo(tmp_path_factory.mktemp("now"), ephemeral=True)
    service._model_settings.update(
        {
            "model": SHARED,
            "agentModels": {"artifact-review": "review-model", "task": "task-model"},
        }
    )
    return service, engine, store


def _event(stage: str, message: str, *, when: datetime = NOW, etype: str = "NOTE") -> Observation:
    return Observation(
        id=f"e-{abs(hash((stage, message, etype))) % 999999}",
        event=ActivityEvent(
            id=f"e-{abs(hash((stage, message, etype))) % 999999}",
            timestamp=when,
            project_id="vhpc",
            task_id="fix-bug",
            workflow_id="software-development",
            event_type=etype,
            message=message,
            metadata={"stage": stage},
        ),
    )


def _run(store, run_id: str, stage: str, **kw) -> WorkflowExecution:
    run = WorkflowExecution(
        id=run_id,
        task_id="fix-bug",
        project_id="vhpc",
        state=RunState(stage=stage, revisions=kw.get("revisions", {})),
        definition={"id": "software-development"},
        started_at=NOW,
        updated_at=NOW,
        in_flight=kw.get("in_flight"),
        retry_at=kw.get("retry_at"),
        retry_attempts=kw.get("retry_attempts", 0),
        context=kw.get("context", {}),
        observations=kw.get("observations", []),
    )
    store.create_execution(run)
    return run


def _view(service, run_id: str) -> dict:
    # The service caches its run list briefly; a run created a moment
    # ago is invisible until the cache lapses, so drop it explicitly.
    service._runs_cache = None
    view = service.get_workflow(run_id)
    assert view is not None
    return view


def _activity(service, run) -> dict:
    activity = _view(service, run.id)["currentActivity"]
    assert activity is not None
    return activity


# -- phases through the real service ------------------------------------


def test_producing_step_names_agent_and_shared_model(demo):
    service, _engine, store = demo
    run = _run(store, "now-prod", "IMPLEMENTING", in_flight="t")
    activity = _activity(service, run)
    assert activity["phase"] == "PRODUCING"
    assert activity["agentId"] == "agent-implement"
    assert activity["agentName"] == "Implementation Agent"
    assert activity["model"] == SHARED
    assert activity["attempt"] is None and activity["attemptMax"] is None


def test_per_agent_model_override_wins(demo):
    service, _engine, store = demo
    run = _run(store, "now-task", "TASK_DRAFT", in_flight="t")
    activity = _activity(service, run)
    assert activity["agentId"] == "agent-task"
    assert activity["model"] == "task-model"


def test_ai_reviewing_first_and_last_round(demo):
    service, _engine, store = demo
    first = _activity(service, _run(store, "now-ai1", "SPEC_REVIEW"))
    assert first["phase"] == "AI_REVIEWING"
    assert first["agentId"] == "agent-artifact-review"
    assert first["agentName"] == "Artifact Review Agent"
    assert first["model"] == "review-model"
    assert (first["attempt"], first["attemptMax"]) == (1, 4)
    last = _activity(service, _run(store, "now-ai4", "SPEC_REVIEW", revisions={"spec": 3}))
    assert (last["attempt"], last["attemptMax"]) == (4, 4)


def test_human_approval_has_no_agent_or_model(demo):
    service, _engine, store = demo
    run = _run(
        store,
        "now-human",
        "SPEC_REVIEW",
        context={"approval": {"overrides": {"mode": "human"}}},
    )
    activity = _activity(service, run)
    assert activity["phase"] == "WAITING_FOR_APPROVAL"
    assert activity["agentId"] is None and activity["agentName"] is None
    assert activity["model"] is None


def test_running_tests_never_names_a_model(demo):
    service, _engine, store = demo
    activity = _activity(service, _run(store, "now-test", "TESTING", in_flight="t"))
    assert activity["phase"] == "RUNNING_TESTS"
    assert activity["agentId"] == "agent-test"
    assert activity["model"] is None


def test_fixing_attempts_across_the_budget(demo):
    service, _engine, store = demo
    first = _activity(service, _run(store, "now-fix1", "CODE_FIX", in_flight="t"))
    assert first["phase"] == "FIXING" and first["agentId"] == "agent-fix"
    assert (first["attempt"], first["attemptMax"]) == (1, 3)
    last = _activity(
        service, _run(store, "now-fix3", "CODE_FIX", revisions={FIX_STEP: 2}, in_flight="t")
    )
    assert (last["attempt"], last["attemptMax"]) == (3, 3)


def test_fix_budget_exhausted_escalates_with_attempt(demo):
    service, _engine, store = demo
    run = _run(store, "now-fesc", "CODE_FIX_ESCALATED", revisions={FIX_STEP: 3})
    activity = _activity(service, run)
    assert activity["phase"] == "ESCALATED"
    assert (activity["attempt"], activity["attemptMax"]) == (3, 3)
    assert activity["agentId"] is None and activity["model"] is None


def test_artifact_escalation_mirrors_the_waiting_budget(demo):
    service, _engine, store = demo
    run = _run(store, "now-sesc", "SPEC_ESCALATED", revisions={"spec": 4})
    view = _view(service, run.id)
    activity = view["currentActivity"]
    assert activity["phase"] == "ESCALATED"
    assert activity["agentId"] is None and activity["model"] is None
    budget = view["waiting"]["budget"]
    assert activity["attempt"] == budget["used"]
    assert activity["attemptMax"] == budget["max"]


def test_ci_and_merge_phases_have_no_agent_or_model(demo):
    service, _engine, store = demo
    ci = _activity(service, _run(store, "now-ci", "CI", in_flight="t"))
    assert ci["phase"] == "WAITING_ON_CI"
    assert ci["agentId"] is None and ci["model"] is None
    merge = _activity(service, _run(store, "now-merge", "READY_TO_MERGE", in_flight="t"))
    assert merge["phase"] == "WAITING_FOR_MERGE"
    assert merge["agentId"] is None and merge["model"] is None


def test_ci_retry_attempts_first_and_last(demo):
    service, _engine, store = demo
    retry_at = NOW + timedelta(seconds=30)
    first = _activity(service, _run(store, "now-cir1", "CI", retry_at=retry_at))
    assert first["phase"] == "RETRYING"
    assert (first["attempt"], first["attemptMax"]) == (1, 120)
    last = _activity(
        service, _run(store, "now-cir120", "CI", retry_at=retry_at, retry_attempts=119)
    )
    assert (last["attempt"], last["attemptMax"]) == (120, 120)


# -- events ---------------------------------------------------------------


def test_recent_events_are_stage_filtered_capped_and_ordered(demo):
    service, _engine, store = demo
    trail = [_event("SPEC", f"earlier {i}") for i in range(3)]
    trail += [_event("IMPLEMENTING", f"step {i}") for i in range(12)]
    run = _run(store, "now-events", "IMPLEMENTING", in_flight="t", observations=trail)
    activity = _activity(service, run)
    assert [e["message"] for e in activity["recentEvents"]] == [f"step {i}" for i in range(2, 12)]
    assert activity["lastEventAt"] is not None


def test_recent_event_messages_are_redacted_and_capped(demo):
    service, _engine, store = demo
    secret = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    run = _run(
        store,
        "now-redact",
        "IMPLEMENTING",
        in_flight="t",
        observations=[_event("IMPLEMENTING", f"leaked {secret} " + "y" * 400)],
    )
    activity = _activity(service, run)
    message = activity["recentEvents"][0]["message"]
    assert secret not in message
    assert len(message) <= 240


def test_quiet_run_has_fields_but_no_events(demo):
    service, _engine, store = demo
    activity = _activity(service, _run(store, "now-quiet", "IMPLEMENTING", in_flight="t"))
    assert activity["lastEventAt"] is None
    assert activity["recentEvents"] == []


def test_terminal_run_has_no_activity_at_all(demo):
    service, _engine, store = demo
    run = _run(store, "now-done", "COMPLETED")
    view = _view(service, run.id)
    assert view["currentActivity"] is None


# -- the list endpoints must not grow -------------------------------------


def test_list_workflow_activity_is_unenriched(demo):
    service, _engine, store = demo
    run = _run(store, "now-listed", "IMPLEMENTING", in_flight="t")
    service._runs_cache = None
    listed = {w["id"]: w for w in service.list_workflows()}
    activity = listed[run.id]["currentActivity"]
    assert activity is not None
    assert not (NEW_KEYS & set(activity)), NEW_KEYS & set(activity)
    detail = _view(service, run.id)["currentActivity"]
    assert set(detail) >= NEW_KEYS


# -- derivations that need a step the shipped definition lacks ------------


def _stub_service(step, *, kind="RETRY_WAIT", revisions=None):
    waiting = {"kind": kind, "round": None, "maxRounds": None, "budget": None}
    return SimpleNamespace(
        _waiting=lambda run, status: waiting,
        _workflow_status=lambda run: "WAITING_RETRY",
        _step_for_stage=lambda run, stage: step,
        _fix_budget=lambda run: {"used": 0, "max": 3},
        _metadata=lambda agent_id: SimpleNamespace(name="Spec Agent"),
        _agent_id_for_type=lambda agent_type: "agent-spec",
        _model_settings=SimpleNamespace(effective_model=lambda agent, tier=None: "m"),
    )


def _bare_run(stage: str, **kw) -> WorkflowExecution:
    return WorkflowExecution(
        id="bare",
        task_id="t",
        project_id="p",
        state=RunState(stage=stage, revisions=kw.get("revisions", {})),
        definition={"id": "d"},
        started_at=NOW,
        updated_at=NOW,
        retry_attempts=kw.get("retry_attempts", 0),
    )


def _policy_step(max_attempts: int = 3):
    return SimpleNamespace(
        action=None,
        agent_type="spec",
        retry_policy=SimpleNamespace(max_attempts=max_attempts),
    )


def test_step_retry_attempts_first_last_and_running():
    service = _stub_service(_policy_step())
    base = {"kind": "RETRY_WAIT"}
    first = enrich_activity(service, _bare_run("SPEC", retry_attempts=0), dict(base))
    assert (first["attempt"], first["attemptMax"]) == (1, 3)
    last = enrich_activity(service, _bare_run("SPEC", retry_attempts=2), dict(base))
    assert (last["attempt"], last["attemptMax"]) == (3, 3)
    running = enrich_activity(
        _stub_service(_policy_step(), kind="STEP_RUNNING"),
        _bare_run("SPEC", retry_attempts=1),
        {"kind": "STEP_RUNNING"},
    )
    assert running["phase"] == "PRODUCING"
    assert (running["attempt"], running["attemptMax"]) == (2, 3)


def test_unidentifiable_step_leaves_phase_null_but_keeps_events():
    service = _stub_service(None, kind="STEP_RUNNING")
    run = _bare_run("SPEC")
    run.observations = [_event("SPEC", "hello")]
    enriched = enrich_activity(service, run, {"kind": "STEP_RUNNING"})
    assert enriched["phase"] is None and enriched["agentId"] is None
    assert enriched["lastEventAt"] is not None
    assert [e["message"] for e in enriched["recentEvents"]] == ["hello"]
