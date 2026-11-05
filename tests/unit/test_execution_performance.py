"""Performance-shape tests: cheap snapshots, batched observation
delivery, summary-driven list views.

These assert COUNTS (saves, payload loads), never wall-clock time:
with 200 pending observations, delivery performs exactly one store
save; with 50 stored runs, repeat list calls perform zero per-run
payload loads.
"""

from __future__ import annotations

import copy
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from asf.api.service import FactoryService
from asf.contracts.models import ActivityEvent
from asf.orchestrator.engine import Orchestrator
from asf.orchestrator.execution import Observation, WorkflowExecution
from asf.orchestrator.registry import AgentRegistry
from asf.state_machine.machine import RunState
from asf.storage.mariadb import (
    _MIGRATIONS,
    MariaDbApprovalRepository,
    MariaDbConfig,
    MariaDbExecutionStore,
)
from asf.storage.sqlite import SQLiteExecutionStore
from asf.workflow.definition import WorkflowDefinition
from tests.unit.test_api_service import PROJECTS, FakeMetrics, RoutingGateway
from tests.unit.test_orchestrator_concurrency import InMemoryExecutionStore
from tests.unit.test_workspace_concurrency import build_engine

NOW = datetime(2026, 11, 5, 16, 0, tzinfo=timezone.utc)


# -- A: snapshots ---------------------------------------------------------


def test_snapshot_is_an_independent_copy_and_run_state_deep_copies():
    state = RunState(stage="SPEC_REVIEW", revisions={"spec": 2})
    cloned = copy.deepcopy(state)
    assert cloned == state
    assert cloned.revisions == {"spec": 2}

    run = WorkflowExecution(
        id="run-1", task_id="t", project_id="p", state=state,
        definition={"id": "development"},
        started_at=NOW, updated_at=NOW,
        context={"nested": {"count": 1}},
    )
    snap = run.snapshot()
    assert snap is not run
    snap.context["nested"]["count"] = 99
    assert run.context["nested"]["count"] == 1


def test_engine_get_copy_semantics():
    from tests.unit.test_orchestrator import make_engine

    engine, _spec, _plan, _repo = make_engine()
    started = engine.start(
        task_id="task-1", project_id="project-1",
        inputs={"spec": {"requirement": "Add a feature"}},
    )
    live_a = engine.get(started.id, copy=False)
    live_b = engine.get(started.id, copy=False)
    assert live_a is live_b  # internal read-only path: no copy at all
    public = engine.get(started.id)
    assert public is not live_a
    assert public.id == live_a.id


# -- B: batched observation delivery ---------------------------------------


class _CountingStore(InMemoryExecutionStore):
    def __init__(self) -> None:
        super().__init__()
        self.saves = 0

    def save_execution(self, run: WorkflowExecution) -> None:
        self.saves += 1
        super().save_execution(run)


class _Publisher:
    def __init__(self, fail_on: int | None = None) -> None:
        self.events: list[ActivityEvent] = []
        self.fail_on = fail_on

    def publish(self, event: ActivityEvent) -> None:
        if self.fail_on is not None and len(self.events) + 1 == self.fail_on:
            raise RuntimeError("publisher down")
        self.events.append(event)


class _Metrics:
    def __init__(self) -> None:
        self.recorded: list[str] = []

    def record(
        self, agent_id: str, result: Any, *, run_id: str | None = None,
    ) -> None:
        self.recorded.append(agent_id)


def _make_store_engine(store: _CountingStore, publisher: _Publisher):
    from tests.unit.test_orchestrator import step

    ids = iter(f"id-{n}" for n in range(1, 100_000))
    definition = WorkflowDefinition(
        id="development", name="Development", version="1",
        steps=[step("spec")],
    )
    engine = Orchestrator(
        definition, AgentRegistry(), clock=lambda: NOW,
        new_id=lambda: next(ids), store=store, events=publisher,
        metrics=_Metrics(),
    )
    return engine


def _seed_observations(store: _CountingStore, run_id: str, count: int) -> None:
    stored = store.get_execution(run_id)
    for index in range(count):
        stored.observations.append(Observation(
            id=f"obs-{index}",
            event=ActivityEvent(
                id=f"evt-{index}", timestamp=NOW, project_id="project-1",
                task_id="task-1", workflow_id="development",
                event_type="TEST_EVENT", message=f"event {index}",
            ),
        ))
    store.save_execution(stored)


def test_delivering_200_observations_saves_exactly_once():
    store = _CountingStore()
    publisher = _Publisher()
    engine = _make_store_engine(store, publisher)
    started = engine.start(task_id="task-1", project_id="project-1")
    _seed_observations(store, started.id, 200)
    store.saves = 0
    engine.flush_observations(started.id)
    assert store.saves == 1
    assert len(publisher.events) >= 200
    stored = store.get_execution(started.id)
    assert all(item.delivered for item in stored.observations)


def test_failed_delivery_marks_only_the_successful_prefix():
    store = _CountingStore()
    # The run's own WORKFLOW_STARTED observation publishes first, so
    # failing the 4th publish strands obs-2 onwards.
    publisher = _Publisher(fail_on=4)
    engine = _make_store_engine(store, publisher)
    started = engine.start(task_id="task-1", project_id="project-1")
    _seed_observations(store, started.id, 5)
    store.saves = 0
    with pytest.raises(RuntimeError, match="remains pending"):
        engine.flush_observations(started.id)
    assert store.saves == 1  # the successful prefix is marked in one save
    stored = store.get_execution(started.id)
    by_id = {item.id: item.delivered for item in stored.observations}
    seeded = [by_id[f"obs-{index}"] for index in range(5)]
    assert seeded == [True, True, False, False, False]


# -- C: summaries ------------------------------------------------------------


def _execution(run_id: str, task_id: str, stage: str) -> WorkflowExecution:
    return WorkflowExecution(
        id=run_id, task_id=task_id, project_id="proj-1",
        state=RunState(stage=stage), definition={"id": "software-development"},
        started_at=NOW, updated_at=NOW,
    )


def test_sqlite_summaries_are_light_and_filterable(tmp_path: Path):
    store = SQLiteExecutionStore(tmp_path / "runs.sqlite")
    store.create_execution(_execution("run-1", "task-a", "COMPLETED"))
    store.create_execution(_execution("run-2", "task-b", "FAILED"))
    summaries = store.list_execution_summaries("proj-1")
    assert {row["id"] for row in summaries} == {"run-1", "run-2"}
    row = next(item for item in summaries if item["id"] == "run-1")
    assert row["taskId"] == "task-a"
    assert row["stage"] == "COMPLETED" and row["status"] == "COMPLETED"
    assert row["workflowId"] == "software-development"
    assert "payload" not in row and "observations" not in row
    failed = store.list_execution_summaries(status="FAILED")
    assert [item["id"] for item in failed] == ["run-2"]
    assert store.list_execution_summaries("other-project") == []
    store.close()


class _CountingSQLiteStore:
    """Delegates to a real SQLite store while counting payload loads."""

    def __init__(self, inner: SQLiteExecutionStore) -> None:
        self._inner = inner
        self.get_calls = 0
        self.list_calls = 0
        self.summary_calls = 0

    @property
    def approvals(self):  # noqa: ANN202
        return self._inner.approvals

    def transaction(self):  # noqa: ANN202
        return self._inner.transaction()

    def create_execution(self, run: WorkflowExecution) -> None:
        self._inner.create_execution(run)

    def save_execution(self, run: WorkflowExecution) -> None:
        self._inner.save_execution(run)

    def get_execution(self, run_id: str, *, for_update: bool = False):
        self.get_calls += 1
        return self._inner.get_execution(run_id, for_update=for_update)

    def list_executions(self, project_id: str):
        self.list_calls += 1
        return self._inner.list_executions(project_id)

    def list_execution_summaries(self, project_id=None, **kwargs):  # noqa: ANN202
        self.summary_calls += 1
        return self._inner.list_execution_summaries(project_id, **kwargs)


def _service_with_50_stored_runs(tmp_path: Path) -> tuple[FactoryService, _CountingSQLiteStore]:
    inner = SQLiteExecutionStore(tmp_path / "runs.sqlite")
    for index in range(50):
        inner.create_execution(_execution(
            f"run-{index:02d}", f"task-{index:02d}", "COMPLETED",
        ))
    store = _CountingSQLiteStore(inner)
    service = FactoryService(
        build_engine(RoutingGateway()), projects=PROJECTS,
        metrics=FakeMetrics(), clock=lambda: NOW, store=store,
    )
    return service, store


def test_list_tasks_with_50_runs_loads_no_payloads_on_repeat_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    service, store = _service_with_50_stored_runs(tmp_path)
    try:
        first = service.list_tasks()
        assert len(first) == 50
        assert store.get_calls == 50  # cold cache: each run loaded once
        store.get_calls = 0
        # Force re-discovery on every call: even without the TTL
        # cache, summaries show nothing changed, so no payload loads.
        monkeypatch.setattr(FactoryService, "_RUNS_CACHE_TTL_SECONDS", 0)
        for _ in range(3):
            assert len(service.list_tasks()) == 50
        assert store.get_calls == 0
        assert store.list_calls == 0
        assert store.summary_calls >= 3
    finally:
        service.shutdown()


def test_runs_list_is_cached_within_the_ttl(tmp_path: Path):
    service, store = _service_with_50_stored_runs(tmp_path)
    try:
        service.list_tasks()
        calls_after_first = store.summary_calls
        service.list_tasks()
        service.list_workflows()
        assert store.summary_calls == calls_after_first  # TTL cache hit
    finally:
        service.shutdown()


# -- C/D: MariaDB SQL shape (fake connection) ---------------------------------


class _FakeCursor:
    def __init__(self, connection: _FakeConnection) -> None:
        self._connection = connection
        self.rowcount = 1

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        self._connection.statements.append((sql, params))

    def fetchone(self):  # noqa: ANN202
        return self._connection.fetchone_result

    def fetchall(self):  # noqa: ANN202
        return self._connection.fetchall_result


class _FakeConnection:
    def __init__(self) -> None:
        self.statements: list[tuple[str, Any]] = []
        self.fetchone_result: Any = (1,)
        self.fetchall_result: list[Any] = []

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    def ping(self, reconnect: bool = False) -> None:
        return None

    def close(self) -> None:
        return None


def _mariadb_store(connection: _FakeConnection) -> MariaDbExecutionStore:
    store = MariaDbExecutionStore.__new__(MariaDbExecutionStore)
    store._config = MariaDbConfig(database="asf")
    store._local = threading.local()
    store._local.connection = connection
    store._max_allowed_packet = None
    store._packet_warned = set()
    store.approvals = MariaDbApprovalRepository(store._connection)
    return store


def test_mariadb_save_writes_metadata_columns_and_summaries_read_them():
    connection = _FakeConnection()
    store = _mariadb_store(connection)
    run = _execution("run-1", "task-a", "COMPLETED")
    store.save_execution(run)
    sql, params = connection.statements[-1]
    assert "task_id = %s" in sql and "stage = %s" in sql
    assert "updated_at = %s" in sql and "WHERE id = %s AND version = %s" in sql
    assert "task-a" in params and "COMPLETED" in params

    connection.fetchall_result = [(
        "run-1", "proj-1", "task-a", "software-development", "COMPLETED",
        "COMPLETED", NOW, NOW,
    )]
    summaries = store.list_execution_summaries("proj-1", status="COMPLETED")
    sql, params = connection.statements[-1]
    assert "payload" not in sql.split("FROM")[0]
    assert "project_id = %s" in sql and "status = %s" in sql
    assert summaries[0]["taskId"] == "task-a"
    assert summaries[0]["updatedAt"].endswith("Z")


def test_mariadb_approvals_query_by_column_not_by_loading_all():
    connection = _FakeConnection()
    store = _mariadb_store(connection)
    store.approvals.list_pending()
    sql, params = connection.statements[-1]
    assert "WHERE status = %s" in sql and params == ("PENDING",)
    store.approvals.list_by_task("task-a")
    sql, params = connection.statements[-1]
    assert "WHERE task_id = %s" in sql and params == ("task-a",)


def test_mariadb_payload_size_warning_fires_once_per_run(
    caplog: pytest.LogCaptureFixture,
):
    connection = _FakeConnection()
    store = _mariadb_store(connection)
    store._max_allowed_packet = 100  # payload of any real run exceeds 50
    run = _execution("run-1", "task-a", "COMPLETED")
    with caplog.at_level(logging.WARNING, logger="asf.storage.mariadb"):
        store.save_execution(run)
        store.save_execution(run)
    warnings = [
        record for record in caplog.records
        if "max_allowed_packet" in record.getMessage()
    ]
    assert len(warnings) == 1


def test_migration_v3_backfills_from_the_payload_and_adds_indexes():
    versions = dict(_MIGRATIONS)
    assert 3 in versions
    joined = "\n".join(versions[3])
    assert "$.state.stage" in joined and "$.definition.id" in joined
    assert "$.task_id" in joined and "$.requested_at" in joined
    assert "idx_executions_project_updated" in joined
    assert "idx_executions_status" in joined
    assert "idx_approvals_status" in joined and "idx_approvals_task" in joined
    assert "WHERE task_id IS NULL" in joined and "WHERE status IS NULL" in joined
