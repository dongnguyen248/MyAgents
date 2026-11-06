"""Undo journal units: record, revert, conflicts, caps, persistence."""

from __future__ import annotations

from pathlib import Path

import pytest

from asf.tools import journal as journal_module
from asf.tools.changeset import ChangeSet, FileChange
from asf.tools.journal import JournalError, JournalStore


def _changeset(*changes: FileChange) -> ChangeSet:
    return ChangeSet(changes=list(changes))


def _create(path: str, content: str) -> FileChange:
    return FileChange(path=path, operation="create", content=content)


def _modify(path: str, content: str) -> FileChange:
    return FileChange(path=path, operation="modify", content=content)


def _delete(path: str) -> FileChange:
    return FileChange(path=path, operation="delete")


def _journal(tmp_path: Path, root: Path):
    store = JournalStore(tmp_path / "journals")
    return store, store.get_or_create("proj", "run-1", root)


def test_revert_restores_modified_removes_created_restores_deleted(tmp_path: Path):
    root = tmp_path / "folder"
    root.mkdir()
    (root / "a.txt").write_text("old a", encoding="utf-8")
    (root / "gone.txt").write_text("old gone", encoding="utf-8")
    _store, journal = _journal(tmp_path, root)
    changes = _changeset(
        _modify("a.txt", "new a"),
        _create("b.txt", "new b"),
        _delete("gone.txt"),
    )
    journal.record_originals(root, [change.path for change in changes.changes])
    (root / "a.txt").write_text("new a", encoding="utf-8")
    (root / "b.txt").write_text("new b", encoding="utf-8")
    (root / "gone.txt").unlink()
    journal.note_written(changes)

    report = journal.revert(root)

    assert report.conflicts == ()
    assert (root / "a.txt").read_text(encoding="utf-8") == "old a"
    assert not (root / "b.txt").exists()
    assert (root / "gone.txt").read_text(encoding="utf-8") == "old gone"


def test_revert_never_clobbers_a_user_edit(tmp_path: Path):
    root = tmp_path / "folder"
    root.mkdir()
    (root / "a.txt").write_text("old", encoding="utf-8")
    _store, journal = _journal(tmp_path, root)
    changes = _changeset(_modify("a.txt", "asf version"))
    journal.record_originals(root, ["a.txt"])
    (root / "a.txt").write_text("asf version", encoding="utf-8")
    journal.note_written(changes)
    (root / "a.txt").write_text("user version", encoding="utf-8")

    report = journal.revert(root)

    assert report.conflicts == ("a.txt",)
    assert report.reverted == ()
    assert (root / "a.txt").read_text(encoding="utf-8") == "user version"
    loaded = JournalStore(tmp_path / "journals").load("proj", "run-1")
    assert loaded is not None and loaded.last_conflicts == ["a.txt"]


def test_revert_conflicts_when_user_recreates_a_deleted_file(tmp_path: Path):
    root = tmp_path / "folder"
    root.mkdir()
    (root / "a.txt").write_text("old", encoding="utf-8")
    _store, journal = _journal(tmp_path, root)
    changes = _changeset(_delete("a.txt"))
    journal.record_originals(root, ["a.txt"])
    (root / "a.txt").unlink()
    journal.note_written(changes)
    (root / "a.txt").write_text("user recreation", encoding="utf-8")

    report = journal.revert(root)

    assert report.conflicts == ("a.txt",)
    assert (root / "a.txt").read_text(encoding="utf-8") == "user recreation"


def test_rebaseline_advances_the_undo_point(tmp_path: Path):
    root = tmp_path / "folder"
    root.mkdir()
    (root / "a.txt").write_text("v0", encoding="utf-8")
    _store, journal = _journal(tmp_path, root)
    green = _changeset(_modify("a.txt", "v1 green"))
    journal.record_originals(root, ["a.txt"])
    (root / "a.txt").write_text("v1 green", encoding="utf-8")
    journal.note_written(green)
    journal.rebaseline()

    broken = _changeset(_modify("a.txt", "v2 broken"))
    (root / "a.txt").write_text("v2 broken", encoding="utf-8")
    journal.note_written(broken)
    report = journal.revert(root)

    assert report.conflicts == ()
    assert (root / "a.txt").read_text(encoding="utf-8") == "v1 green"


def test_oversized_original_fails_loudly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    root = tmp_path / "folder"
    root.mkdir()
    (root / "big.bin").write_bytes(b"x" * 64)
    _store, journal = _journal(tmp_path, root)
    monkeypatch.setattr(journal_module, "MAX_JOURNAL_FILE_BYTES", 16)
    with pytest.raises(JournalError, match="per-file cap"):
        journal.record_originals(root, ["big.bin"])


def test_run_total_cap_fails_loudly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "folder"
    root.mkdir()
    (root / "a.txt").write_bytes(b"x" * 32)
    (root / "b.txt").write_bytes(b"y" * 32)
    _store, journal = _journal(tmp_path, root)
    monkeypatch.setattr(journal_module, "MAX_JOURNAL_RUN_BYTES", 48)
    with pytest.raises(JournalError, match="exceed"):
        journal.record_originals(root, ["a.txt", "b.txt"])


def test_store_round_trip_and_discard(tmp_path: Path):
    root = tmp_path / "folder"
    root.mkdir()
    (root / "a.txt").write_text("old", encoding="utf-8")
    store, journal = _journal(tmp_path, root)
    journal.record_originals(root, ["a.txt"])
    loaded = store.load("proj", "run-1")
    assert loaded is not None
    assert loaded.state == "active"
    assert loaded.files_written() == ["a.txt"]
    assert loaded.root == root
    store.discard("proj", "run-1")
    assert store.load("proj", "run-1") is None


def test_store_rejects_unsafe_ids(tmp_path: Path):
    store = JournalStore(tmp_path / "journals")
    with pytest.raises(ValueError):
        store.path_for("proj", "../escape")
    assert store.load("proj", "../escape") is None


def test_all_journals_skips_unreadable_files(tmp_path: Path):
    store = JournalStore(tmp_path / "journals")
    journal = store.get_or_create("proj", "run-1", tmp_path)
    journal.record_originals(tmp_path, [])
    journal.save()
    broken = tmp_path / "journals" / "proj" / "broken.json"
    broken.parent.mkdir(parents=True, exist_ok=True)
    broken.write_text("not json", encoding="utf-8")
    assert [item.run_id for item in store.all_journals()] == ["run-1"]
