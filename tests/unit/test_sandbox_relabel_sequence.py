"""Regression: the FIX-3 incident sequence, end to end on a real worktree.

v1 creates a file and is applied; the test verdict fails; the Fix
agent's v2 labels the same file "modify"; before v2 is applied the
worktree is reset to HEAD, which deletes the uncommitted v1 file.
Applying v2 must succeed by treating the modify (which carries the
full content) as a create — before the fix this died with
SandboxError "Cannot modify missing file" and the run failed at the
test step with an opaque SANDBOX_ERROR on every Resume.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from asf.tools.changeset import ChangeSet, FileChange
from asf.tools.local import LocalSandbox
from asf.tools.ports import AppliedRelabel
from asf.tools.worktree import GitWorktreeWorkspace

_PATH = "docs/testing/decisions.md"


def _git(repo: Path, *args: str) -> None:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"git {args} failed: {proc.stderr}"


def _make_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.name", "Test User")
    _git(path, "config", "user.email", "test@example.com")
    (path / "app.py").write_text("VALUE = 'base'\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-m", "base")
    return path


def test_fix_modify_after_worktree_reset_applies_as_create(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")
    workspace = GitWorktreeWorkspace(tmp_path / "worktrees")
    worktree = workspace.ensure(repo, "proj", "run-1", "main")
    target = worktree / _PATH

    v1 = ChangeSet(changes=[FileChange(path=_PATH, operation="create", content="decisions v1\n")])
    LocalSandbox(worktree).run([], v1, "main")
    assert target.read_text(encoding="utf-8") == "decisions v1\n"

    assert workspace.reset_if_dirty(worktree)
    assert not target.exists()

    v2 = ChangeSet(changes=[FileChange(path=_PATH, operation="modify", content="decisions v2\n")])
    result = LocalSandbox(worktree).run([], v2, "main")
    assert result.relabels == (AppliedRelabel(_PATH, "modify", "create"),)
    assert target.read_text(encoding="utf-8") == "decisions v2\n"
