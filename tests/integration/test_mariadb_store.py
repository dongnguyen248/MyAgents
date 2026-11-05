"""MariaDB execution store against a real server (opt-in).

Skipped unless ASF_TEST_MARIADB=1. Connection settings come from the
usual ASF_MARIADB_* variables; the database is ASF_TEST_MARIADB_DATABASE
(default "asf_test") so a development database is never touched. The
account needs privileges on that database only (GRANT ALL ON asf_test.*)
— the store creates the database and tables itself.
"""

from __future__ import annotations

import os
import threading
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from asf.api.demo import build_demo
from asf.orchestrator.execution import WorkflowExecution
from asf.state_machine.machine import RunState
from asf.storage.mariadb import MariaDbConfig, MariaDbExecutionStore

pytestmark = pytest.mark.skipif(
    os.environ.get("ASF_TEST_MARIADB") != "1",
    reason="set ASF_TEST_MARIADB=1 (plus ASF_MARIADB_*) to run against MariaDB",
)


def make_store() -> MariaDbExecutionStore:
    config = replace(
        MariaDbConfig.from_env(),
        database=os.environ.get("ASF_TEST_MARIADB_DATABASE", "asf_test"),
    )
    return MariaDbExecutionStore(config)


def test_store_round_trip_and_reopen(tmp_path: Path):
    project_id = f"itest-{uuid4().hex[:8]}"
    store = make_store()
    service, engine, _ = build_demo(tmp_path / "anchor.sqlite", store=store)
    run = service.start_run(
        "maria-task",
        project_id,
        inputs={"spec": {"requirement": "Persist me"}},
    )
    engine.tick(run.id)  # SPEC -> SPEC_REVIEW (an approval row is written)
    pending = store.approvals.list_pending()
    assert any(a.task_id == "maria-task" for a in pending)
    approval_id = next(a.id for a in pending if a.task_id == "maria-task")
    engine.decide(run.id, reviewer="dashboard", decision="APPROVED")
    assert store.approvals.list_decisions(approval_id)
    store.close()

    # A fresh store on the same server sees everything (nothing was local).
    reopened = make_store()
    try:
        executions = reopened.list_executions(project_id)
        assert [item.id for item in executions] == [run.id]
        assert reopened.get_execution(run.id).task_id == "maria-task"
        with pytest.raises(KeyError):
            reopened.get_execution("no-such-run")
        with pytest.raises(KeyError):
            reopened.save_execution(
                executions[0].model_copy(
                    update={"id": "no-such-run"},
                )
            )
    finally:
        reopened.close()


def test_transaction_rolls_back_on_error(tmp_path: Path):
    project_id = f"itest-{uuid4().hex[:8]}"
    store = make_store()
    try:
        _service, engine, _ = build_demo(tmp_path / "anchor.sqlite", store=store)
        run = engine.start(
            task_id="tx-task",
            project_id=project_id,
            inputs={"spec": {"requirement": "Roll me back"}},
        )
        # engine.start already persisted the run inside its own transaction;
        # a failing transaction must leave the stored payload untouched.
        before = store.get_execution(run.id).model_dump_json()
        with pytest.raises(RuntimeError, match="boom"), store.transaction():
            store.save_execution(run)
            raise RuntimeError("boom")
        assert store.get_execution(run.id).model_dump_json() == before
    finally:
        store.close()


def test_store_supports_concurrent_threads():
    """Same guarantee as the SQLite store: per-thread connections make
    concurrent transactions from many threads land cleanly."""
    project_id = f"itest-{uuid4().hex[:8]}"
    store = make_store()
    errors: list[BaseException] = []

    def worker(index: int) -> None:
        try:
            for number in range(5):
                now = datetime.now(UTC)
                run = WorkflowExecution(
                    id=f"run-{index}-{number}-{uuid4().hex[:8]}",
                    task_id="task-1",
                    project_id=project_id,
                    state=RunState(stage="SPEC_DRAFT"),
                    started_at=now,
                    updated_at=now,
                )
                with store.transaction():
                    store.create_execution(run)
                assert store.get_execution(run.id).id == run.id
        except BaseException as error:  # noqa: BLE001 — collected + asserted
            errors.append(error)

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    try:
        assert errors == []
        assert len(store.list_executions(project_id)) == 40
    finally:
        store.close()


def test_version_guard_rejects_a_stale_save():
    """Optimistic locking on the real server: migration 2 added the
    version column, and a writer holding a stale copy must fail with
    ConcurrentModificationError instead of overwriting (lost update).
    """
    from asf.orchestrator.ports import ConcurrentModificationError

    store = make_store()
    now = datetime.now(UTC)
    run = WorkflowExecution(
        id=f"versioned-{uuid4().hex[:8]}",
        task_id="task-1",
        project_id=f"itest-{uuid4().hex[:8]}",
        state=RunState(stage="SPEC_DRAFT"),
        started_at=now,
        updated_at=now,
    )
    try:
        with store.transaction():
            store.create_execution(run)
        first = store.get_execution(run.id)
        second = store.get_execution(run.id)
        assert first.version == second.version == 0
        first.context["writer"] = "first"
        with store.transaction():
            store.save_execution(first)
        assert first.version == 1
        second.context["writer"] = "second"
        with pytest.raises(ConcurrentModificationError), store.transaction():
            store.save_execution(second)
        saved = store.get_execution(run.id)
        assert saved.version == 1
        assert saved.context["writer"] == "first"
        # The claim phase's locking read works inside a transaction.
        with store.transaction():
            locked = store.get_execution(run.id, for_update=True)
        assert locked.id == run.id
    finally:
        store.close()


def test_long_running_agent_holds_no_row_lock():
    """Deadlock/lock-wait proof on the real server.

    A dispatch claims its run (SELECT ... FOR UPDATE + version-guarded
    UPDATE) in a short transaction and then executes WITHOUT holding
    the row. While a slow agent runs, a competing claim on the SAME
    row — on a connection whose innodb_lock_wait_timeout is only 2
    seconds — must be refused immediately by the in_flight check. If
    the executing dispatch still held the row lock, the competing
    claim's FOR UPDATE would instead die with a lock-wait timeout
    (error 1205) after ~2 s.
    """
    import threading
    import time
    from itertools import count

    from asf.agents.base import AgentRuntime
    from asf.contracts.models import AgentMetadata, Artifact
    from asf.models.fake import ScriptedModelGateway
    from asf.orchestrator import AgentRegistry, Orchestrator
    from asf.workflow.definition import WorkflowDefinition, WorkflowStepDef
    from tests.unit.test_agent_base import DummyAgent

    store = make_store()
    now = datetime.now(UTC)
    ids = count(1)
    runtime = AgentRuntime(
        models=ScriptedModelGateway([]),
        clock=lambda: now,
        new_id=lambda: f"id-{next(ids)}",
    )
    entered = threading.Event()
    calls: list[str] = []

    def slow_produce(request):
        calls.append(request.task_id)
        entered.set()
        time.sleep(3)
        artifact = Artifact(
            id=f"art-{next(ids)}",
            type="SPEC",
            name="spec",
            version="1",
            content={"text": "spec"},
            created_by="agent-spec",
            created_at=now,
        )
        return {"summary": "done"}, [artifact]

    agent = DummyAgent(
        runtime,
        metadata=AgentMetadata(
            id="agent-spec",
            name="spec",
            type="spec",
            version="1",
            status="IDLE",
        ),
        run_behavior=slow_produce,
    )
    registry = AgentRegistry()
    registry.register(agent)
    definition = WorkflowDefinition(
        id="development",
        name="Development",
        version="1",
        steps=[
            WorkflowStepDef(
                id="spec",
                name="spec",
                type="AGENT",
                stage="SPEC",
                agent_type="spec",
                requires_approval=False,
                consumes=[],
                produces=["SPEC"],
            )
        ],
    )

    def make_engine() -> Orchestrator:
        return Orchestrator(
            definition,
            registry,
            clock=lambda: now,
            new_id=lambda: f"run-{uuid4().hex[:8]}",
            store=store,
        )

    engine_a, engine_b = make_engine(), make_engine()
    run = engine_a.start(
        task_id="lock-task",
        project_id=f"itest-{uuid4().hex[:8]}",
        inputs={"spec": {"requirement": "Slow"}},
    )
    errors: list[BaseException] = []

    def dispatch() -> None:
        try:
            engine_a.tick(run.id)
        except BaseException as error:  # noqa: B036 - asserted below
            errors.append(error)

    thread = threading.Thread(target=dispatch)
    thread.start()
    try:
        assert entered.wait(timeout=10), "agent never started"
        outcome: dict[str, object] = {}

        def competing_claim() -> None:
            connection = store._connection()  # this thread's own
            with connection.cursor() as cursor:
                cursor.execute("SET SESSION innodb_lock_wait_timeout = 2")
            began = time.monotonic()
            try:
                engine_b.tick(run.id)
                outcome["result"] = "ticked"
            except BaseException as error:  # noqa: B036 - asserted below
                outcome["result"] = error
            outcome["elapsed"] = time.monotonic() - began

        rival = threading.Thread(target=competing_claim)
        rival.start()
        rival.join(timeout=15)
        assert not rival.is_alive()
        # Refused fast by the in_flight check — NOT a lock-wait
        # timeout (pymysql OperationalError 1205) and not a dispatch.
        assert isinstance(outcome["result"], ValueError), outcome["result"]
        assert outcome["elapsed"] < 2
    finally:
        thread.join(timeout=15)
    assert not thread.is_alive()
    assert errors == []
    assert calls == ["lock-task"]  # the agent ran exactly once
    assert engine_a.get(run.id).artifacts.get("SPEC") is not None
    store.close()


def test_summaries_and_migration_v3_backfill():
    """Metadata columns: saves populate them, summaries read only
    them, and the v3 backfill UPDATE (the exact statement shipped in
    _MIGRATIONS) repairs rows whose columns were never written."""
    from asf.storage.mariadb import _MIGRATIONS

    project_id = f"itest-{uuid4().hex[:8]}"
    store = make_store()
    try:
        run = WorkflowExecution(
            id=f"run-{uuid4().hex[:8]}",
            task_id="backfill-task",
            project_id=project_id,
            state=RunState(stage="COMPLETED"),
            definition={"id": "software-development"},
            started_at=datetime(2026, 11, 5, 9, 0, tzinfo=UTC),
            updated_at=datetime(2026, 11, 5, 9, 30, tzinfo=UTC),
        )
        store.create_execution(run)
        summaries = store.list_execution_summaries(project_id)
        assert [row["id"] for row in summaries] == [run.id]
        assert summaries[0]["taskId"] == "backfill-task"
        assert summaries[0]["stage"] == "COMPLETED"
        assert summaries[0]["workflowId"] == "software-development"

        # Simulate a pre-v3 row: columns NULL, payload intact. Running
        # the shipped backfill statement must restore them.
        with store._connection().cursor() as cursor:
            cursor.execute(
                "UPDATE executions SET task_id = NULL, stage = NULL,"
                " status = NULL, workflow_id = NULL, started_at = NULL,"
                " updated_at = NULL WHERE id = %s",
                (run.id,),
            )
        backfill = next(
            statement
            for statement in dict(_MIGRATIONS)[3]
            if statement.strip().startswith("UPDATE executions")
        )
        with store._connection().cursor() as cursor:
            cursor.execute(backfill)
        summaries = store.list_execution_summaries(project_id)
        assert summaries[0]["taskId"] == "backfill-task"
        assert summaries[0]["stage"] == "COMPLETED"
        assert summaries[0]["startedAt"].startswith("2026-11-05T09:00:00")
        assert summaries[0]["updatedAt"].startswith("2026-11-05T09:30:00")
        # The status filter rides the indexed status column.
        assert (
            store.list_execution_summaries(
                project_id,
                status="FAILED",
            )
            == []
        )
        assert [
            row["id"]
            for row in store.list_execution_summaries(
                project_id,
                status="COMPLETED",
            )
        ] == [run.id]
    finally:
        store.close()


def test_approval_queries_use_their_indexes():
    """EXPLAIN must show index access (not a full table scan) for the
    two approval list queries and the summaries query."""
    store = make_store()
    try:
        checks = [
            (
                "SELECT payload FROM approvals WHERE status = %s ORDER BY requested_at, id",
                ("PENDING",),
                "idx_approvals_status",
            ),
            (
                "SELECT payload FROM approvals WHERE task_id = %s ORDER BY requested_at, id",
                ("some-task",),
                "idx_approvals_task",
            ),
            (
                "SELECT id FROM executions WHERE project_id = %s ORDER BY updated_at, id",
                ("some-project",),
                "idx_executions_project_updated",
            ),
        ]
        with store._connection().cursor() as cursor:
            for sql, params, expected_key in checks:
                cursor.execute(f"EXPLAIN {sql}", params)
                rows = cursor.fetchall()
                # EXPLAIN columns: id, select_type, table, type, ...
                # key is column 6 (index 5) in the classic format.
                used_keys = {row[5] for row in rows}
                access_types = {row[3] for row in rows}
                assert expected_key in used_keys, (sql, rows)
                assert "ALL" not in access_types, (sql, rows)
    finally:
        store.close()
