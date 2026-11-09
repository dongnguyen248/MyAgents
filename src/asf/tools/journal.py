"""Undo journal for direct workspace mode.

In direct mode a run writes its change sets straight into the
project's own folder (``repository.path``) instead of a per-run git
worktree. The journal is what makes that safe to undo: before the run
first writes a path, the journal records the path's original bytes —
or that it was absent — in a JSON file under the backend's data
directory::

    <journals_root>/<project_id>/<run_id>.json

State convention (mirrors the worktree convention in
``asf.tools.worktree``):

- Before a replacement change set is applied (the Fix loop), the
  journal reverts the folder to the last green state: the pre-run
  state, advanced every time a test step passes (the direct-mode
  equivalent of the worktree's green commit).
- A run that ends FAILED or CANCELLED is reverted; a COMPLETED run
  keeps its files and its journal is discarded. Nothing is ever
  committed anywhere — in a git folder the files simply stay as
  uncommitted changes for the user to review.
- Reverting never clobbers user edits: a file is restored only while
  its current bytes still equal what ASF last wrote. A file the user
  touched in the meantime is skipped and reported as a conflict.
- Journal size is capped per file and per run; a file whose original
  bytes exceed the cap fails the apply loudly instead of being
  written without an undo record.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from asf.tools.changeset import ChangeSet
from asf.tools.ports import SandboxError
from asf.tools.worktree import validate_run_id

__all__ = [
    "MAX_JOURNAL_FILE_BYTES",
    "MAX_JOURNAL_RUN_BYTES",
    "JournalError",
    "JournalStore",
    "RevertReport",
    "RunJournal",
]

#: Largest original file the journal will record. Bigger files fail
#: the apply loudly rather than being written without an undo record.
MAX_JOURNAL_FILE_BYTES = 1_048_576

#: Largest total of original bytes one run's journal will record.
MAX_JOURNAL_RUN_BYTES = 16_777_216

_PROJECT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

#: Journal states. "active" while the run can still write; the others
#: are the terminal outcomes surfaced on the run.
JOURNAL_ACTIVE = "active"
JOURNAL_REVERTED = "reverted"
JOURNAL_KEPT = "kept"
JOURNAL_CONFLICT = "conflict"


class JournalError(SandboxError):
    """The undo journal could not record or restore a file."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _validate_project_id(project_id: str) -> str:
    if not _PROJECT_ID_PATTERN.match(project_id or "") or project_id in {".", ".."}:
        raise ValueError(f"Project id {project_id!r} is not a safe path part")
    return project_id


@dataclass(frozen=True)
class RevertReport:
    """Outcome of one journal revert: restored paths, skipped paths."""

    reverted: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()


@dataclass
class RunJournal:
    """One run's undo record over one project folder.

    Each entry maps a repository-relative path to its ``original``
    state (``{"absent": True}`` or the original bytes, base64) and the
    ``written`` state ASF last produced (a sha256, ``{"absent": True}``
    after a delete, or None when nothing was written yet — a revert
    then expects the file to still be in its original state).
    """

    project_id: str
    run_id: str
    root: Path
    store_path: Path
    state: str = JOURNAL_ACTIVE
    entries: dict[str, dict] = field(default_factory=dict)
    last_conflicts: list[str] = field(default_factory=list)

    def record_originals(self, root: Path, paths: Iterable[str]) -> None:
        """Records pre-write state for paths the journal does not know.

        Raises JournalError when a file (or the run total) exceeds
        the journal caps: the apply must fail loudly rather than
        write a file that cannot be undone.
        """
        total = self._recorded_bytes()
        added = False
        for relative in paths:
            if relative in self.entries:
                continue
            original, size = self._read_original(root, relative)
            total += size
            if total > MAX_JOURNAL_RUN_BYTES:
                raise JournalError(
                    f"Undo journal for run {self.run_id} would exceed "
                    f"{MAX_JOURNAL_RUN_BYTES} bytes of originals; refusing "
                    f"to write {relative} without an undo record",
                )
            self.entries[relative] = {"original": original, "written": None}
            added = True
        if added:
            self.save()

    def _read_original(self, root: Path, relative: str) -> tuple[dict, int]:
        target = root / Path(*relative.split("/"))
        if not target.is_file():
            return {"absent": True}, 0
        size = target.stat().st_size
        if size > MAX_JOURNAL_FILE_BYTES:
            raise JournalError(
                f"File {relative} is {size} bytes, over the undo journal's "
                f"per-file cap of {MAX_JOURNAL_FILE_BYTES}; refusing to "
                "write it without an undo record",
            )
        data = target.read_bytes()
        return {"sha256": _sha256(data), "data": base64.b64encode(data).decode()}, size

    def _recorded_bytes(self) -> int:
        total = 0
        for entry in self.entries.values():
            original = entry["original"]
            if "data" in original:
                total += len(base64.b64decode(original["data"]))
        return total

    def note_written(self, changes: ChangeSet) -> None:
        """Records what ASF's apply produced, per changed path."""
        for change in changes.changes:
            entry = self.entries.get(change.path)
            if entry is None:
                continue
            if change.operation == "delete":
                entry["written"] = {"absent": True}
            else:
                entry["written"] = {"sha256": _sha256((change.content or "").encode())}
        self.save()

    def rebaseline(self) -> None:
        """Advances the undo baseline to the folder's current state.

        Called when a test step passes: the current bytes become the
        "originals" a later revert restores — the direct-mode
        equivalent of committing the green worktree state.
        """
        for relative, entry in self.entries.items():
            original, _size = self._read_original(self.root, relative)
            entry["original"] = original
            entry["written"] = (
                {"absent": True} if "absent" in original else {"sha256": original["sha256"]}
            )
        self.save()

    def revert(self, root: Path) -> RevertReport:
        """Restores every journaled path the user has not edited.

        A path is restored only while its current state still equals
        what ASF last wrote (or its original state when nothing was
        written); otherwise it is left exactly as the user has it and
        reported as a conflict.
        """
        reverted: list[str] = []
        conflicts: list[str] = []
        for relative in sorted(self.entries):
            outcome = self._revert_one(root, relative, self.entries[relative])
            if outcome:
                # The path is back at its original state; a later
                # revert must expect that, not the pre-revert write.
                self.entries[relative]["written"] = None
                reverted.append(relative)
            else:
                conflicts.append(relative)
        self.last_conflicts = conflicts
        self.save()
        return RevertReport(reverted=tuple(reverted), conflicts=tuple(conflicts))

    def _revert_one(self, root: Path, relative: str, entry: dict) -> bool:
        target = root / Path(*relative.split("/"))
        current = self._current_state(target)
        written = entry["written"]
        expected = written if written is not None else _state_of(entry["original"])
        if current != expected:
            return False
        original = entry["original"]
        if "absent" in original:
            if target.is_file():
                target.unlink()
            return True
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(base64.b64decode(original["data"]))
        return True

    @staticmethod
    def _current_state(target: Path) -> dict:
        if not target.is_file():
            return {"absent": True}
        return {"sha256": _sha256(target.read_bytes())}

    def files_written(self) -> list[str]:
        return sorted(self.entries)

    def save(self) -> None:
        payload = {
            "projectId": self.project_id,
            "runId": self.run_id,
            "root": str(self.root),
            "state": self.state,
            "entries": self.entries,
            "conflicts": self.last_conflicts,
        }
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.store_path.write_text(json.dumps(payload, indent=1), encoding="utf-8")


def _state_of(original: dict) -> dict:
    """The comparable state dict of a recorded original."""
    if "absent" in original:
        return {"absent": True}
    return {"sha256": original["sha256"]}


class JournalStore:
    """Owns the journal files of every direct-mode project."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    @property
    def root(self) -> Path:
        return self._root

    def path_for(self, project_id: str, run_id: str) -> Path:
        _validate_project_id(project_id)
        validate_run_id(run_id)
        path = (self._root / project_id / f"{run_id}.json").resolve()
        if not path.is_relative_to(self._root.resolve()):
            raise ValueError("Journal path escapes the journals root")
        return path

    def load(self, project_id: str, run_id: str) -> RunJournal | None:
        try:
            path = self.path_for(project_id, run_id)
        except ValueError:
            return None
        return self._read(path)

    def get_or_create(self, project_id: str, run_id: str, root: Path) -> RunJournal:
        existing = self.load(project_id, run_id)
        if existing is not None:
            return existing
        return RunJournal(
            project_id=project_id,
            run_id=run_id,
            root=Path(root),
            store_path=self.path_for(project_id, run_id),
        )

    def discard(self, project_id: str, run_id: str) -> None:
        try:
            path = self.path_for(project_id, run_id)
        except ValueError:
            return
        path.unlink(missing_ok=True)

    def all_journals(self) -> list[RunJournal]:
        """Every readable journal on disk (unreadable ones are skipped)."""
        journals: list[RunJournal] = []
        if not self._root.is_dir():
            return journals
        for path in sorted(self._root.glob("*/*.json")):
            journal = self._read(path)
            if journal is not None:
                journals.append(journal)
        return journals

    def _read(self, path: Path) -> RunJournal | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return RunJournal(
                project_id=str(payload["projectId"]),
                run_id=str(payload["runId"]),
                root=Path(str(payload["root"])),
                store_path=path,
                state=str(payload.get("state", JOURNAL_ACTIVE)),
                entries=dict(payload.get("entries", {})),
                last_conflicts=[str(path) for path in payload.get("conflicts", [])],
            )
        except (OSError, ValueError, KeyError, TypeError):
            return None
