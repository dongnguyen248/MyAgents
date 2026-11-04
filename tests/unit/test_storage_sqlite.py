"""SQLite execution store: database file handling."""

from __future__ import annotations

from pathlib import Path

import pytest

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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
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
