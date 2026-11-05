"""Operator run controls: escalation resume, recover, drive, fail,
pause/continue — plus the resume_failed budget reset and the
configurable code-loop budget.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import asf.api.demo as demo_module
from asf.api.app import create_app
from asf.api.demo import build_demo
from asf.configuration.platform import PlatformConfig
from asf.orchestrator.code_loop import FIX_STEP
from asf.orchestrator.ports import ConcurrentModificationError
from asf.state_machine.machine import RunState

NOW = datetime(2026, 11, 5, 19, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    service, engine, store = build_demo(tmp_path_factory.mktemp("operator"), ephemeral=True)
    return service, engine, store


@pytest.fixture(scope="module")
def client(demo):
    service, _engine, _store = demo
    return TestClient(create_app(service))


def _start(service) -> str:
    run = service.start_run(
        "task-op", "vhpc", inputs={"spec": {"requirement": "Build a calculator"}}
    )
    service.wait_for_drives(timeout=10)
    return run.id


def _force(engine, run_id: str, stage: str, **updates) -> None:
    with engine._edit(run_id) as stored:
        stored.state = RunState(
            stage=stage, revisions=dict(updates.pop("revisions", stored.state.revisions))
        )
        stored.approval_id = None
        for key, value in updates.items():
            setattr(stored, key, value)


def _events(engine, run_id: str, event_type: str) -> list:
    return [
        obs.event
        for obs in engine.get(run_id).observations
        if obs.event is not None and obs.event.event_type == event_type
    ]


# -- escalation resume ------------------------------------------------------


def test_escalation_resume_requires_reason(client, demo):
    service, engine, _store = demo
    run_id = _start(service)
    _force(engine, run_id, "CODE_FIX_ESCALATED", revisions={FIX_STEP: 3})
    assert client.post(f"/runs/{run_id}/escalation/resume", json={}).status_code == 422
    assert (
        client.post(f"/runs/{run_id}/escalation/resume", json={"reason": "   "}).status_code == 422
    )
    assert (
        client.post(f"/runs/{run_id}/escalation/resume", json={"reason": "x" * 501}).status_code
        == 422
    )


def test_escalation_resume_grants_exactly_one_fresh_budget(client, demo):
    service, engine, _store = demo
    run_id = _start(service)
    # Paused so the post-resume background drive cannot move the
    # run while the assertions read it back.
    _force(engine, run_id, "CODE_FIX_ESCALATED", revisions={FIX_STEP: 3}, paused=True)
    response = client.post(
        f"/runs/{run_id}/escalation/resume",
        json={"reason": "fixed the prompt, try again"},
        headers={"X-Operator": "dong"},
    )
    assert response.status_code == 200
    run = engine.get(run_id)
    assert run.state.stage == "CODE_FIX"
    assert run.state.revisions[FIX_STEP] == 1
    resumed = _events(engine, run_id, "WORKFLOW_RESUMED")
    assert resumed[-1].metadata["reason"] == "fixed the prompt, try again"
    assert resumed[-1].metadata["operator"] == "dong"


def test_resumed_budget_is_exactly_one_full_budget(demo):
    # Engine-level (no background drive racing the assertions): a
    # resumed run fits exactly max_fixes fix dispatches before it
    # escalates again — one fresh budget, not two, not zero. Each
    # verdict cycle runs inside an edit, the way the engine's own
    # commit does, so the revision counter actually persists.
    service, engine, _store = demo
    run_id = _start(service)
    _force(engine, run_id, "CODE_FIX_ESCALATED", revisions={FIX_STEP: 3})
    engine.resume(run_id, reason="grant another round")

    def verdict_requests_changes() -> object:
        with engine._edit(run_id) as stored:
            stored.state = RunState(stage="CODE_REVIEW", revisions=dict(stored.state.revisions))
            engine._request_fix(stored)
        return engine.get(run_id)

    # Resume itself dispatched fix #1 (counter at 1); fixes #2 and
    # #3 follow, and the request after #3 escalates.
    for expected in (2, 3):
        run = verdict_requests_changes()
        assert run.state.stage == "CODE_FIX"
        assert run.state.revisions[FIX_STEP] == expected
    run = verdict_requests_changes()
    assert run.state.stage == "CODE_FIX_ESCALATED"


def test_escalation_resume_rejects_non_escalated_run(client, demo):
    service, _engine, _store = demo
    run_id = _start(service)  # parked at the spec gate
    response = client.post(f"/runs/{run_id}/escalation/resume", json={"reason": "try anyway"})
    assert response.status_code == 409
    assert "not escalated" in response.json()["detail"]


def test_operator_conflict_maps_to_409(demo, monkeypatch):
    service, engine, _store = demo
    run_id = _start(service)
    _force(engine, run_id, "CODE_FIX_ESCALATED", revisions={FIX_STEP: 3})

    def conflict(*args, **kwargs):
        raise ConcurrentModificationError("version moved")

    monkeypatch.setattr(engine, "resume", conflict)
    with pytest.raises(ValueError, match="changed concurrently"):
        service.resume_escalation(run_id, reason="go")


# -- recover ------------------------------------------------------------------


def test_recover_refused_while_drive_is_live(client, demo):
    service, engine, _store = demo
    run_id = _start(service)
    _force(engine, run_id, "IMPLEMENTING", in_flight="token-live")
    service._drive_active.add(run_id)
    try:
        response = client.post(f"/runs/{run_id}/recover", json={"reason": "looks stuck"})
        assert response.status_code == 409
        assert "actively being driven" in response.json()["detail"]
    finally:
        service._drive_active.discard(run_id)


def test_recover_accepted_when_in_flight_is_overdue(client, demo):
    service, engine, _store = demo
    run_id = _start(service)
    _force(
        engine,
        run_id,
        "IMPLEMENTING",
        in_flight="token-stale",
        updated_at=datetime.now(UTC) - timedelta(seconds=2000),
    )
    response = client.post(
        f"/runs/{run_id}/recover",
        json={"reason": "step is lost", "retryInterrupted": True},
    )
    assert response.status_code == 200
    run = engine.get(run_id)
    assert run.in_flight is None
    assert run.state.stage == "IMPLEMENTING"  # replay: not failed
    recovered = _events(engine, run_id, "WORKFLOW_RECOVERED")
    assert recovered and recovered[-1].metadata["reason"] == "step is lost"


def test_recover_without_replay_fails_the_run(client, demo):
    service, engine, _store = demo
    run_id = _start(service)
    _force(engine, run_id, "IMPLEMENTING", in_flight="token-stale")
    response = client.post(f"/runs/{run_id}/recover", json={"reason": "do not replay"})
    assert response.status_code == 200
    assert engine.get(run_id).state.stage == "FAILED"


# -- drive + fail ----------------------------------------------------------------


def test_drive_endpoint_is_idempotent(client, demo):
    service, _engine, _store = demo
    run_id = _start(service)
    assert client.post(f"/runs/{run_id}/drive").status_code == 200
    assert client.post(f"/runs/{run_id}/drive").status_code == 200
    assert client.post("/runs/nope/drive").status_code == 404


def test_fail_escalated_run_then_resume_failed_resets_fix_budget(client, demo):
    service, engine, _store = demo
    run_id = _start(service)
    _force(
        engine,
        run_id,
        "CODE_FIX_ESCALATED",
        revisions={"spec": 2, FIX_STEP: 3},
        attempts={FIX_STEP: 4, "spec": 1},
        retry_attempts=5,
    )
    response = client.post(
        f"/runs/{run_id}/fail",
        json={"reason": "giving up on this approach"},
        headers={"X-Operator": "dong"},
    )
    assert response.status_code == 200
    run = engine.get(run_id)
    assert run.state.stage == "FAILED"
    assert run.errors[-1].code == "OPERATOR_FAILED"
    failed_events = _events(engine, run_id, "RUN_FAILED_BY_OPERATOR")
    assert failed_events[-1].metadata["reason"] == "giving up on this approach"
    assert failed_events[-1].metadata["operator"] == "dong"
    # resume_failed forks: fix budget reset, other counters kept,
    # the failed step's attempt counter restarted, retry count 0.
    fork = engine.resume_failed(run_id)
    assert fork.state.revisions.get(FIX_STEP) is None
    assert fork.state.revisions.get("spec") == 2
    assert fork.retry_attempts == 0
    assert any("Fix budget reset" in note for note in fork.recovery_notes)


def test_fail_rejects_a_healthy_run(client, demo):
    service, _engine, _store = demo
    run_id = _start(service)
    response = client.post(f"/runs/{run_id}/fail", json={"reason": "nope"})
    assert response.status_code == 409


# -- pause / continue -------------------------------------------------------------


def test_pause_blocks_ticks_until_continued(demo):
    service, engine, _store = demo
    run_id = _start(service)  # parked at the spec gate
    view = service.pause_run(run_id, reason="lunch", operator="dong")
    assert view is not None and view["status"] == "PAUSED"
    assert view["waiting"]["kind"] == "PAUSED"
    paused_events = _events(engine, run_id, "RUN_PAUSED")
    assert paused_events[-1].metadata["operator"] == "dong"
    # A manual tick is a no-op while paused.
    before = engine.get(run_id)
    engine.tick(run_id)
    after = engine.get(run_id)
    assert after.state.stage == before.state.stage
    assert after.in_flight is None
    view = service.continue_run(run_id)
    assert view is not None and view["status"] == "WAITING_APPROVAL"
    assert _events(engine, run_id, "RUN_CONTINUED")


# -- configurable budget ------------------------------------------------------------


def test_code_loop_budget_comes_from_platform_config(tmp_path, monkeypatch):
    config = PlatformConfig.model_validate({"version": 1, "codeLoop": {"maxFixes": 5}})
    assert config.code_loop.max_fixes == 5
    monkeypatch.setattr(demo_module, "load_platform_config", lambda _dir: config)
    _service, engine, _store = build_demo(tmp_path, ephemeral=True)
    assert engine._graph.max_revisions[FIX_STEP] == 5


def test_engine_loads_run_across_a_budget_change(tmp_path, monkeypatch):
    """Raising maxFixes and restarting must not orphan stored runs."""
    _service, engine, store = build_demo(tmp_path, ephemeral=True)
    run = engine.start(task_id="task-budget", project_id="vhpc", inputs={})
    bigger = PlatformConfig.model_validate({"version": 1, "codeLoop": {"maxFixes": 9}})
    monkeypatch.setattr(demo_module, "load_platform_config", lambda _dir: bigger)
    _service2, engine2, _store2 = build_demo(tmp_path, store=store)
    assert engine2._graph.max_revisions[FIX_STEP] == 9
    assert engine2.get(run.id).id == run.id
