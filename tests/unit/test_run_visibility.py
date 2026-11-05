"""Run visibility: where is a run, what is it waiting for, why did
it stop — the operator-facing derivations in the workflow view,
the drive's stop bookkeeping, diagnostics and orphan adoption.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from asf.agents.base import AgentRuntime
from asf.api.demo import build_demo
from asf.api.service import FactoryService
from asf.contracts.models import ActivityEvent, Artifact, PlatformError
from asf.models.errors import ModelGatewayError
from asf.models.fake import ScriptedModelGateway
from asf.orchestrator.code_loop import FIX_STEP
from asf.orchestrator.engine import Orchestrator
from asf.orchestrator.execution import Observation, WorkflowExecution
from asf.orchestrator.ports import ConcurrentModificationError
from asf.state_machine.machine import RunState
from asf.workflow.loader import load_workflow
from tests.unit.test_agent_base import T_AWARE, CounterId, CountingClock, DummyAgent, make_request

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 11, 5, 18, 0, tzinfo=UTC)
DEFINITION = load_workflow(ROOT / "workflow-definitions" / "software-development.yaml")


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    service, engine, store = build_demo(tmp_path_factory.mktemp("visibility"), ephemeral=True)
    return service, engine, store


def _artifact(kind: str) -> Artifact:
    return Artifact(
        id=f"{kind.lower()}-1",
        type=kind,
        name=kind.title(),
        version="1",
        content={"text": "x"},
        created_by="agent",
        created_at=NOW,
    )


def _run(
    stage: str,
    *,
    revisions: dict[str, int] | None = None,
    artifacts: tuple[str, ...] = ("SPEC", "PLAN", "TASK", "CODE", "CODE_REVIEW"),
    trail: tuple[str, ...] = (),
    in_flight: str | None = None,
    retry_at: datetime | None = None,
    updated_at: datetime = NOW,
) -> WorkflowExecution:
    produced = {kind: _artifact(kind) for kind in artifacts}
    observations = [
        Observation(
            id=f"obs-{index}",
            event=ActivityEvent(
                id=f"obs-{index}",
                timestamp=NOW,
                project_id="proj-1",
                task_id="task-1",
                workflow_id="software-development",
                event_type="WORKFLOW_STAGE_CHANGED",
                message="stage changed",
                metadata={"stage": trail_stage},
            ),
        )
        for index, trail_stage in enumerate(trail)
    ]
    return WorkflowExecution(
        id="run-1",
        task_id="task-1",
        project_id="proj-1",
        state=RunState(stage=stage, revisions=revisions or {}),
        artifacts=dict(produced),
        artifact_history=dict(produced),
        definition={"id": "software-development"},
        started_at=NOW,
        updated_at=updated_at,
        in_flight=in_flight,
        retry_at=retry_at,
        observations=observations,
    )


def _states(service: FactoryService, run: WorkflowExecution, status: str) -> dict[str, str]:
    steps = service._step_states(run, DEFINITION, status)
    return {step["id"]: step["state"] for step in steps}


# -- _step_states inside the code loop ---------------------------------


@pytest.mark.parametrize(
    ("stage", "status", "expected_fix"),
    [
        ("CODE_FIX", "RUNNING", "active"),
        ("CODE_REWORK", "RUNNING", "rejected"),
        ("CODE_FIX_ESCALATED", "ESCALATED", "escalated"),
        ("CODE_FIX", "FAILED", "failed"),
        ("CODE_REWORK", "FAILED", "failed"),
        ("CODE_FIX_ESCALATED", "FAILED", "failed"),
    ],
)
def test_step_states_inside_code_loop(demo, stage, status, expected_fix):
    service, _engine, _store = demo
    run = _run(
        stage if status != "FAILED" else "FAILED",
        revisions={FIX_STEP: 1},
        trail=(stage,) if status == "FAILED" else (),
    )
    states = _states(service, run, status)
    # Everything before the loop is done — never the old all-pending.
    for step_id in (
        "spec",
        "spec_approval",
        "plan",
        "plan_approval",
        "task",
        "task_approval",
        "implementation",
    ):
        assert states[step_id] == "done", (stage, status, step_id)
    assert states["fix"] == expected_fix, (stage, status)
    assert states["ci"] == "pending" and states["merge"] == "pending"


def test_step_states_loop_cycle_and_label(demo):
    service, _engine, _store = demo
    run = _run("CODE_FIX", revisions={FIX_STEP: 2})
    steps = service._step_states(run, DEFINITION, "RUNNING")
    by_id = {step["id"]: step for step in steps}
    assert by_id["code_review"]["state"] == "done"
    # No TEST_REPORT yet this cycle: testing is still to come.
    assert by_id["testing"]["state"] == "pending"
    assert by_id["fix"]["label"] == "Fix code · fix 2/3"
    # The synthetic step sits between testing and ci.
    ids = [step["id"] for step in steps]
    assert ids.index("testing") < ids.index("fix") < ids.index("ci")
    with_report = _run(
        "CODE_FIX",
        revisions={FIX_STEP: 1},
        artifacts=("SPEC", "PLAN", "TASK", "CODE", "CODE_REVIEW", "TEST_REPORT"),
    )
    states = _states(service, with_report, "RUNNING")
    assert states["testing"] == "done"


def test_step_states_outside_loop_have_no_fix_step(demo):
    service, _engine, _store = demo
    states = _states(service, _run("IMPLEMENTING"), "RUNNING")
    assert "fix" not in states
    assert states["implementation"] == "active"
    assert states["spec"] == "done" and states["testing"] == "pending"


# -- status + waiting ----------------------------------------------------


def test_status_escalated_and_waiting_block(demo):
    service, _engine, _store = demo
    run = _run("CODE_FIX_ESCALATED", revisions={FIX_STEP: 3})
    assert service._workflow_status(run) == "ESCALATED"
    waiting = service._waiting(run, "ESCALATED")
    assert waiting["kind"] == "ESCALATED"
    assert waiting["budget"] == {"used": 3, "max": 3}
    assert waiting["suggestedActions"] == ["resume", "cancel"]
    assert "fix budget" in waiting["reason"]


def test_status_waiting_retry(demo):
    service, _engine, _store = demo
    run = _run("IMPLEMENTING", retry_at=NOW + timedelta(seconds=30))
    assert service._workflow_status(run) == "WAITING_RETRY"
    waiting = service._waiting(run, "WAITING_RETRY")
    assert waiting["kind"] == "RETRY_WAIT"
    assert waiting["retryAt"] is not None


def _service_at(clock_time: datetime, stall_seconds: float = 900):
    """A FactoryService whose clock is frozen, over a stub engine."""
    engine = SimpleNamespace(
        _graph=SimpleNamespace(max_revisions={FIX_STEP: 3}),
        _clock=lambda: clock_time,
    )
    service = FactoryService(
        engine,  # type: ignore[arg-type]
        projects={},
        clock=lambda: clock_time,
        stall_seconds=stall_seconds,
    )
    return service


def test_stalled_when_undriven_and_untouched():
    service = _service_at(NOW + timedelta(seconds=120))
    run = _run("IMPLEMENTING", updated_at=NOW)
    assert service._is_stalled(run, "RUNNING") is True
    waiting = service._waiting(run, "RUNNING")
    assert waiting["kind"] == "STALLED"
    assert waiting["suggestedActions"] == ["adopt", "cancel"]


def test_stalled_when_step_in_flight_past_watchdog():
    service = _service_at(NOW + timedelta(seconds=120), stall_seconds=60)
    run = _run("IMPLEMENTING", in_flight="token-1", updated_at=NOW)
    assert service._is_stalled(run, "RUNNING") is True


def test_not_stalled_when_fresh_or_driven():
    service = _service_at(NOW + timedelta(seconds=30))
    fresh = _run("IMPLEMENTING", updated_at=NOW)
    assert service._is_stalled(fresh, "RUNNING") is False
    assert service._waiting(fresh, "RUNNING")["kind"] == "STEP_RUNNING"


# -- AGENT_FAILED event metadata -----------------------------------------


def test_agent_failed_event_carries_the_error():
    agent = DummyAgent(
        _runtime(),
        run_behavior=ModelGatewayError(
            "LLM_TIMEOUT", "Gateway timed out reading password = 'sup3rsecretvalue9'"
        ),
    )
    result = agent.execute(make_request())
    assert result.status == "FAILED"
    failed = [e for e in result.events if e.event_type == "AGENT_FAILED"]
    assert len(failed) == 1
    metadata = failed[0].metadata
    assert metadata["errorCode"] == "LLM_TIMEOUT"
    assert metadata["errorCategory"] == "LLM"
    assert metadata["retryable"] is True
    assert "sup3rsecretvalue9" not in metadata["errorMessage"]
    assert "[REDACTED]" in metadata["errorMessage"]
    assert len(metadata["errorMessage"]) <= 300


def _runtime():
    return AgentRuntime(
        models=ScriptedModelGateway([]),
        clock=CountingClock(T_AWARE),
        new_id=CounterId(),
    )


# -- fix / escalated event messages ---------------------------------------


def test_fix_and_escalation_messages_differ(demo):
    _service, engine, _store = demo
    run = engine.start(
        task_id="task-x",
        project_id="proj-1",
        inputs={"spec": {"requirement": "x"}},
    )
    with engine._edit(run.id) as stored:
        stored.state = RunState(stage="CODE_REVIEW", revisions={})
    working = engine.get(run.id)
    engine._request_fix(working)
    requested = [
        obs.event.message
        for obs in working.observations
        if obs.event is not None and obs.event.event_type == "CODE_FIX_REQUESTED"
    ]
    assert requested == ["Review/Test requested changes — fix 1/3"]

    with engine._edit(run.id) as stored:
        stored.state = RunState(stage="CODE_REVIEW", revisions={FIX_STEP: 3})
    working = engine.get(run.id)
    engine._request_fix(working)
    escalated = [
        obs.event
        for obs in working.observations
        if obs.event is not None and obs.event.event_type == "WORKFLOW_ESCALATED"
    ]
    assert escalated and "Fix budget exhausted (3/3)" in escalated[0].message
    assert escalated[0].message != requested[0]


# -- DRIVE_STOPPED bookkeeping --------------------------------------------


def _drive_stops(engine: Orchestrator, run_id: str) -> list[dict]:
    return [
        obs.event.metadata
        for obs in engine.get(run_id).observations
        if obs.event is not None and obs.event.event_type == "DRIVE_STOPPED"
    ]


def _start_demo_run(service: FactoryService) -> str:
    run = service.start_run(
        "task-drive",
        "vhpc",
        inputs={"spec": {"requirement": "Build a calculator"}},
    )
    return run.id


def test_drive_records_awaiting_approval(demo):
    service, engine, _store = demo
    run_id = _start_demo_run(service)
    service.wait_for_drives(timeout=10)
    stops = _drive_stops(engine, run_id)
    assert stops and stops[-1]["reason"] == "awaiting_approval"
    assert service.get_workflow(run_id)["driver"]["lastStopReason"] == "awaiting_approval"


def _flaky_tick(engine, fail_from: int, error: Exception):
    real_tick = engine.tick
    calls = {"count": 0}

    def tick(run_id: str):
        calls["count"] += 1
        if calls["count"] >= fail_from:
            raise error
        return real_tick(run_id)

    return tick


def _pump_approvals(service: FactoryService, rounds: int = 8) -> None:
    for _ in range(rounds):
        service.wait_for_drives(timeout=10)
        pending = service.list_approvals()
        if not pending:
            return
        service.decide_approval(pending[0]["id"], decision="APPROVE")


def test_drive_records_error_with_type(demo, monkeypatch):
    service, engine, _store = demo
    monkeypatch.setattr(engine, "tick", _flaky_tick(engine, 3, RuntimeError("tick exploded")))
    run_id = _start_demo_run(service)
    _pump_approvals(service)
    stops = _drive_stops(engine, run_id)
    assert stops[-1]["reason"] == "error"
    assert stops[-1]["errorType"] == "RuntimeError"


def test_drive_records_lost_race_as_warning_not_error(demo, monkeypatch):
    service, engine, _store = demo
    monkeypatch.setattr(
        engine,
        "tick",
        _flaky_tick(engine, 2, ConcurrentModificationError("claimed elsewhere")),
    )
    run_id = _start_demo_run(service)
    _pump_approvals(service)
    stops = _drive_stops(engine, run_id)
    assert stops[-1]["reason"] == "lost_race"
    assert "errorType" not in stops[-1]


def _mutating_tick(engine, mutate):
    real_tick = engine.tick
    calls = {"count": 0}

    def tick(run_id: str):
        calls["count"] += 1
        if calls["count"] == 2:
            mutate(run_id)
            return engine.get(run_id)
        return real_tick(run_id)

    return tick


def test_drive_records_escalated_and_retry_wait(demo, monkeypatch):
    service, engine, _store = demo

    def escalate(run_id: str) -> None:
        with engine._edit(run_id) as stored:
            stored.state = RunState(stage="CODE_FIX_ESCALATED", revisions={FIX_STEP: 3})

    monkeypatch.setattr(engine, "tick", _mutating_tick(engine, escalate))
    run_id = _start_demo_run(service)
    _pump_approvals(service)
    assert _drive_stops(engine, run_id)[-1]["reason"] == "escalated"
    monkeypatch.undo()

    def park(run_id: str) -> None:
        with engine._edit(run_id) as stored:
            stored.state = RunState(stage="IMPLEMENTING", revisions={})
            stored.retry_at = NOW + timedelta(minutes=5)

    monkeypatch.setattr(engine, "tick", _mutating_tick(engine, park))
    run_id = _start_demo_run(service)
    _pump_approvals(service)
    assert _drive_stops(engine, run_id)[-1]["reason"] == "retry_wait"


# -- diagnostics -----------------------------------------------------------


def test_diagnostics_shape(demo):
    service, engine, _store = demo
    run_id = _start_demo_run(service)
    service.wait_for_drives(timeout=10)
    diagnostics = service.run_diagnostics(run_id)
    assert diagnostics is not None
    for key in (
        "stage",
        "stageKind",
        "status",
        "waiting",
        "inFlight",
        "retryAt",
        "fixBudget",
        "revisions",
        "lastEvents",
        "lastError",
        "driver",
        "suggestedActions",
    ):
        assert key in diagnostics, key
    assert diagnostics["status"] == "WAITING_APPROVAL"
    assert diagnostics["waiting"]["kind"] == "APPROVAL"
    assert diagnostics["suggestedActions"] == ["approve", "reject", "cancel"]
    assert len(diagnostics["lastEvents"]) <= 20
    assert service.run_diagnostics("no-such-run") is None


def test_diagnostics_redacts_last_error(demo):
    service, engine, _store = demo
    run_id = _start_demo_run(service)
    with engine._edit(run_id) as stored:
        stored.errors.append(
            PlatformError(
                code="LLM_AUTH_FAILED",
                message="bad credentials password = 'sup3rsecretvalue9'",
                category="LLM",
                retryable=False,
                timestamp=NOW,
            )
        )
    diagnostics = service.run_diagnostics(run_id)
    assert diagnostics is not None and diagnostics["lastError"] is not None
    assert "sup3rsecretvalue9" not in diagnostics["lastError"]["message"]


# -- orphan adoption --------------------------------------------------------


def _force_stage(engine: Orchestrator, run_id: str, stage: str, **updates) -> None:
    with engine._edit(run_id) as stored:
        stored.state = RunState(stage=stage, revisions=dict(stored.state.revisions))
        stored.approval_id = None
        stored.in_flight = None
        for key, value in updates.items():
            setattr(stored, key, value)


def test_adopt_orphans_bounded_at_three(demo, monkeypatch):
    service, engine, _store = demo
    run_id = _start_demo_run(service)
    service.wait_for_drives(timeout=10)
    _force_stage(engine, run_id, "IMPLEMENTING")
    driven: list[str] = []
    monkeypatch.setattr(service, "_drive_in_background", driven.append)
    for _ in range(5):
        service._adopt_orphans()
    # Three adoptions, then the give-up is recorded and driving stops.
    assert driven == [run_id, run_id, run_id]
    stops = _drive_stops(engine, run_id)
    assert stops and stops[-1]["reason"] == "stalled"


def test_adopt_orphans_skips_gated_and_retry_runs(demo, monkeypatch):
    service, engine, _store = demo
    _start_demo_run(service)
    service.wait_for_drives(timeout=10)  # parked at the spec gate
    parked_id = _start_demo_run(service)
    service.wait_for_drives(timeout=10)
    _force_stage(engine, parked_id, "IMPLEMENTING", retry_at=NOW + timedelta(minutes=5))
    driven: list[str] = []
    monkeypatch.setattr(service, "_drive_in_background", driven.append)
    service._adopt_orphans()
    assert driven == []
