"""SQLite execution store: database file handling."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

from asf.orchestrator.execution import WorkflowExecution
from asf.state_machine.machine import RunState
from asf.storage.sqlite import SQLiteExecutionStore


def test_store_creates_missing_parent_directories(tmp_path: Path):
    db_path = tmp_path / "nested" / "deeper" / "asf.sqlite"
    store = SQLiteExecutionStore(db_path)
    try:
        assert db_path.is_file()
        assert store.list_executions("any-project") == []
    finally:
        store.close()


def test_store_accepts_bare_filename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.chdir(tmp_path)
    store = SQLiteExecutionStore("asf.sqlite")
    try:
        assert (tmp_path / "asf.sqlite").is_file()
    finally:
        store.close()


def test_store_in_memory_still_works():
    store = SQLiteExecutionStore(":memory:")
    store.close()


def _execution(run_id: str) -> WorkflowExecution:
    now = datetime.now(UTC)
    return WorkflowExecution(
        id=run_id,
        task_id="task-1",
        project_id="project-1",
        state=RunState(stage="SPEC_DRAFT"),
        started_at=now,
        updated_at=now,
    )


def test_store_supports_concurrent_threads(tmp_path: Path):
    """Drives execute on a background thread while the API serves reads
    on request threads: concurrent transactions from many threads must
    all land, with no cross-thread connection errors."""
    store = SQLiteExecutionStore(tmp_path / "concurrent.sqlite")
    errors: list[BaseException] = []

    def worker(index: int) -> None:
        try:
            for number in range(5):
                run = _execution(f"run-{index}-{number}")
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
        assert len(store.list_executions("project-1")) == 40
    finally:
        store.close()
