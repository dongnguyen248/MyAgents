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
from datetime import datetime, timezone
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
        "maria-task", project_id, inputs={"spec": {"requirement": "Persist me"}},
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
            reopened.save_execution(executions[0].model_copy(
                update={"id": "no-such-run"},
            ))
    finally:
        reopened.close()


def test_transaction_rolls_back_on_error(tmp_path: Path):
    project_id = f"itest-{uuid4().hex[:8]}"
    store = make_store()
    try:
        _service, engine, _ = build_demo(tmp_path / "anchor.sqlite", store=store)
        run = engine.start(
            task_id="tx-task", project_id=project_id,
            inputs={"spec": {"requirement": "Roll me back"}},
        )
        # engine.start already persisted the run inside its own transaction;
        # a failing transaction must leave the stored payload untouched.
        before = store.get_execution(run.id).model_dump_json()
        with pytest.raises(RuntimeError, match="boom"):
            with store.transaction():
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
                now = datetime.now(timezone.utc)
                run = WorkflowExecution(
                    id=f"run-{index}-{number}-{uuid4().hex[:8]}",
                    task_id="task-1", project_id=project_id,
                    state=RunState(stage="SPEC_DRAFT"),
                    started_at=now, updated_at=now,
                )
                with store.transaction():
                    store.create_execution(run)
                assert store.get_execution(run.id).id == run.id
        except BaseException as error:  # noqa: BLE001 — collected + asserted
            errors.append(error)

    threads = [
        threading.Thread(target=worker, args=(index,)) for index in range(8)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    try:
        assert errors == []
        assert len(store.list_executions(project_id)) == 40
    finally:
        store.close()
