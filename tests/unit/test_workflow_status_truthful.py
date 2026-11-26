"""Workflow status truthfulness: a run the engine cannot load must
not be reported as RUNNING.

The engine raises ``ValueError`` for stored runs whose definition or
execution policy no longer matches (legacy runs). The old fallback
mapped every such non-COMPLETED run to RUNNING, so FAILED and
CANCELLED legacy runs looked alive forever in the workflow view, the
Live Map snapshot and the run dropdown.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import pytest

from asf.api.demo import build_demo
from asf.api.service import FactoryService, status_fallback
from asf.api.service.driver import _adoptable
from asf.orchestrator.execution import WorkflowExecution
from asf.state_machine.machine import RunState

NOW = datetime.now(UTC)
LEGACY_DEFINITION = {"id": "software-development", "version": "0.0-legacy"}


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    service, engine, store = build_demo(tmp_path_factory.mktemp("truthful"), ephemeral=True)
    return service, engine, store


@pytest.fixture(autouse=True)
def _clear_seen():
    status_fallback._seen.clear()
    yield
    status_fallback._seen.clear()


class _RaisingEngine:
    """Engine stub whose workflow_run always raises the given error."""

    def __init__(self, error: Exception) -> None:
        self._error = error
        self.calls = 0

    def workflow_run(self, run_id: str) -> dict[str, str]:
        self.calls += 1
        raise self._error


def _service(engine: object) -> FactoryService:
    return FactoryService(engine, projects={}, clock=lambda: NOW)  # type: ignore[arg-type]


def _run(stage: str, run_id: str = "run-1", project_id: str = "proj-1") -> WorkflowExecution:
    return WorkflowExecution(
        id=run_id,
        task_id="task-1",
        project_id=project_id,
        state=RunState(stage=stage, revisions={}),
        artifacts={},
        artifact_history={},
        definition=dict(LEGACY_DEFINITION),
        started_at=NOW,
        updated_at=NOW,
    )


@pytest.mark.parametrize("stage", ["FAILED", "CANCELLED", "COMPLETED"])
def test_terminal_stage_wins_without_touching_the_engine(stage: str) -> None:
    engine = _RaisingEngine(ValueError("Stored workflow definition differs"))
    service = _service(engine)
    assert service._workflow_status(_run(stage)) == stage
    assert engine.calls == 0


def test_non_terminal_stage_with_raising_engine_is_unknown() -> None:
    engine = _RaisingEngine(ValueError("Stored workflow definition differs"))
    service = _service(engine)
    assert service._workflow_status(_run("IMPLEMENTING")) == "UNKNOWN"


def test_service_side_states_survive_engine_failure(demo) -> None:
    # Paused/escalated/retry states derive from the run itself, not
    # the engine; only the fabricated RUNNING becomes UNKNOWN.
    service, _engine, _store = demo
    retrying = _run("IMPLEMENTING")
    retrying.retry_at = NOW
    assert service._workflow_status(retrying) == "WAITING_RETRY"
    assert service._workflow_status(_run("CODE_FIX_ESCALATED")) == "ESCALATED"


def test_engine_failure_logs_once_per_run_and_type(caplog: pytest.LogCaptureFixture) -> None:
    run = _run("IMPLEMENTING")
    with caplog.at_level(logging.WARNING, logger="asf.api.service.status_fallback"):
        status_fallback.engine_status(_RaisingEngine(ValueError("boom")), run)
        status_fallback.engine_status(_RaisingEngine(ValueError("boom")), run)
        status_fallback.engine_status(_RaisingEngine(KeyError("boom")), run)
    records = [record for record in caplog.records if "status unavailable" in record.message]
    assert len(records) == 2


def test_seen_set_is_capped() -> None:
    for index in range(status_fallback._SEEN_CAP + 5):
        status_fallback._log_once(f"run-{index}", ValueError("boom"))
    assert len(status_fallback._seen) == status_fallback._SEEN_CAP
    assert ("run-0", "ValueError") not in status_fallback._seen


def test_task_and_workflow_views_agree_for_unloadable_terminal_run(demo) -> None:
    service, _engine, store = demo
    project_id = next(iter(service._projects))
    run = _run("FAILED", run_id="legacy-failed", project_id=project_id)
    store.create_execution(run)
    view = service.get_workflow("legacy-failed")
    assert view is not None
    assert view["status"] == "FAILED"
    assert view["waiting"]["kind"] == "NONE"
    assert view["waiting"]["suggestedActions"] == []
    assert service._task_status(run) == "FAILED"


def test_unloadable_terminal_run_actions_surface_the_load_failure(demo) -> None:
    # Reproduction for the S0 report: the view offers Resume / Run
    # again for FAILED runs, but every action re-enters the engine
    # load that fails. The API maps ValueError to 409; S0 reports
    # this, it does not fix it.
    service, _engine, store = demo
    project_id = next(iter(service._projects))
    store.create_execution(_run("FAILED", run_id="legacy-actions", project_id=project_id))
    for action in (service.retry_run, service.resume_run, service.cancel_run):
        with pytest.raises(ValueError, match="definition or execution policy differs"):
            action("legacy-actions")


def test_startup_drive_skips_unloadable_non_terminal_run(demo) -> None:
    service, _engine, store = demo
    project_id = next(iter(service._projects))
    run = _run("IMPLEMENTING", run_id="legacy-live", project_id=project_id)
    store.create_execution(run)
    service.drive_active_runs()
    assert "legacy-live" not in service._drive_active
    assert service._workflow_status(run) == "UNKNOWN"


def test_adoptable_rejects_unknown_status() -> None:
    run = _run("IMPLEMENTING")
    assert _adoptable(run, set(), None, "UNKNOWN") is False


def test_waiting_for_unknown_claims_no_step_and_no_actions(demo) -> None:
    service, _engine, _store = demo
    waiting = service._waiting(_run("IMPLEMENTING"), "UNKNOWN")
    assert waiting["kind"] == "NONE"
    assert waiting["suggestedActions"] == []
