"""Per-run git worktrees for local projects.

Writing change sets straight into the user's working tree (the old
Local Workspace behaviour) leaves a failed or cancelled run's
half-applied code behind, and two runs of one project trample each
other. When a project's folder is a git repository, each run instead
works in its OWN worktree:

    <worktrees_root>/<project_id>/<run_id>/   on branch asf/<run_id>

created from the step's ref (default HEAD). State convention:

- The test sandbox resets a dirty worktree to HEAD before applying a
  new change set, so a fix's replacement CODE lands on the last
  committed (passing) state, never layered over the broken attempt.
- When a test step reports PASS, the worktree is committed (message
  names the task item and the CODE artifact id/version), so the next
  item — and the fix loop's baseline — build on green state.
- When a run ends FAILED or CANCELLED its worktree and branch are
  removed (configurable); a COMPLETED run's worktree is kept so the
  user can review and merge branch ``asf/<run_id>`` themselves.
- At startup, :meth:`GitWorktreeWorkspace.sweep` removes orphaned
  worktrees: directories whose run is unknown to the run store or
  ended FAILED/CANCELLED.

Projects whose folder is NOT a git repository keep the old direct
behaviour — the workspace logs a loud warning (see
``asf.tools.local``) because their runs have no isolation or
rollback.

Git is only ever invoked as an argv list (never through a shell),
paths are absolute and root-checked, and run ids / branch names are
validated against a conservative pattern before they reach a command
line or a path.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import threading
from collections.abc import Callable, Mapping
from pathlib import Path

from asf.tools.ports import SandboxError

__all__ = ["GitWorktreeWorkspace", "WorktreeError", "validate_run_id"]

logger = logging.getLogger(__name__)

#: Run ids become branch names (``asf/<run_id>``) and directory
#: names: start alphanumeric, then alphanumerics, dash, underscore.
#: This is a subset of what git accepts as a ref component, so a
#: validated id is always a safe branch suffix and a safe path part.
_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_PROJECT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

_GIT_TIMEOUT_SECONDS = 180
_COMMITTER = ("-c", "user.name=AI Software Agents", "-c", "user.email=asf@localhost")


class WorktreeError(SandboxError):
    """A git worktree operation failed."""


def validate_run_id(run_id: str) -> str:
    if not _RUN_ID_PATTERN.match(run_id or ""):
        raise ValueError(
            f"Run id {run_id!r} is not safe for a worktree branch/path",
        )
    return run_id


def _validate_project_id(project_id: str) -> str:
    if not _PROJECT_ID_PATTERN.match(project_id or "") or project_id in {".", ".."}:
        raise ValueError(f"Project id {project_id!r} is not a safe path part")
    return project_id


def _validate_ref(ref: str) -> str:
    """A committish passed as one argv element: no option injection."""
    if not ref or ref.startswith("-") or any(ch.isspace() for ch in ref):
        raise ValueError(f"Unsafe git ref {ref!r}")
    return ref


def run_git(repo: Path, *args: str) -> str:
    """Runs git in ``repo`` (argv list, no shell) and returns stdout."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, text=True, errors="replace",
            timeout=_GIT_TIMEOUT_SECONDS, check=False,
        )
    except OSError as error:
        raise WorktreeError(f"Could not run git in {repo}: {error}") from None
    except subprocess.TimeoutExpired:
        raise WorktreeError(
            f"git {' '.join(args[:2])} timed out in {repo}",
        ) from None
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        raise WorktreeError(
            f"git {' '.join(args)} failed in {repo}: "
            f"{detail[-1] if detail else 'unknown error'}",
        )
    return proc.stdout


class GitWorktreeWorkspace:
    """Owns the worktree directories of every local git project."""

    def __init__(
        self, worktrees_root: Path, *, cleanup_completed: bool = False,
    ) -> None:
        self._root = Path(worktrees_root)
        self._cleanup_completed = cleanup_completed
        self._ensure_lock = threading.Lock()
        self._git_cache: dict[Path, bool] = {}

    @property
    def root(self) -> Path:
        return self._root

    # -- discovery ------------------------------------------------------

    def is_git_repo(self, path: Path) -> bool:
        cached = self._git_cache.get(path)
        if cached is None:
            try:
                run_git(path, "rev-parse", "--git-dir")
                cached = True
            except WorktreeError:
                cached = False
            self._git_cache[path] = cached
        return cached

    def worktree_path(self, project_id: str, run_id: str) -> Path:
        _validate_project_id(project_id)
        validate_run_id(run_id)
        path = (self._root / project_id / run_id).resolve()
        if not path.is_relative_to(self._root.resolve()):
            raise ValueError("Worktree path escapes the worktrees root")
        return path

    def has_worktree(self, project_id: str, run_id: str) -> bool:
        try:
            return (self.worktree_path(project_id, run_id) / ".git").exists()
        except ValueError:
            return False

    # -- lifecycle --------------------------------------------------------

    def ensure(
        self, project_root: Path, project_id: str, run_id: str, ref: str,
    ) -> Path:
        """Creates the run's worktree if needed and returns its path."""
        path = self.worktree_path(project_id, run_id)
        if (path / ".git").exists():
            return path
        ref = _validate_ref(ref or "HEAD")
        branch = f"asf/{run_id}"
        with self._ensure_lock:
            if (path / ".git").exists():
                return path
            path.parent.mkdir(parents=True, exist_ok=True)
            existing = run_git(project_root, "branch", "--list", branch).strip()
            if existing:
                # A kept branch from an earlier finish (e.g. a run
                # resumed after the backend restarted): reopen it.
                run_git(project_root, "worktree", "add", str(path), branch)
            else:
                run_git(
                    project_root, "worktree", "add", "-b", branch,
                    str(path), ref,
                )
            logger.info(
                "Created worktree for run %s of project %s at %s (branch %s)",
                run_id, project_id, path, branch,
            )
            return path

    def reset_if_dirty(self, worktree: Path) -> bool:
        """Resets a worktree to HEAD when it holds uncommitted changes.

        Untracked files are cleaned too: change-set "create" semantics
        need the previously applied (unpassed) files gone. Only ASF
        worktrees are ever reset — everything untracked in them was
        put there by ASF steps or the test commands they ran.
        """
        if not run_git(worktree, "status", "--porcelain").strip():
            return False
        run_git(worktree, "reset", "--hard", "HEAD")
        run_git(worktree, "clean", "-fd")
        return True

    def commit_all(self, worktree: Path, message: str) -> str | None:
        """Commits every worktree change; returns the new HEAD or None."""
        run_git(worktree, "add", "-A")
        if not run_git(worktree, "status", "--porcelain").strip():
            return None
        run_git(worktree, *_COMMITTER, "commit", "-m", message)
        return run_git(worktree, "rev-parse", "HEAD").strip()

    def remove(self, project_root: Path, project_id: str, run_id: str) -> bool:
        """Removes the run's worktree and its branch. Idempotent."""
        path = self.worktree_path(project_id, run_id)
        removed = False
        if path.exists():
            try:
                run_git(project_root, "worktree", "remove", "--force", str(path))
            except WorktreeError:
                shutil.rmtree(path, ignore_errors=True)
                try:
                    run_git(project_root, "worktree", "prune")
                except WorktreeError:
                    pass
            removed = True
        branch = f"asf/{run_id}"
        if run_git(project_root, "branch", "--list", branch).strip():
            run_git(project_root, "branch", "-D", branch)
            removed = True
        return removed

    def finish(
        self, project_root: Path, project_id: str, run_id: str, stage: str,
    ) -> str:
        """Applies the end-of-run cleanup policy; returns the action."""
        if stage in {"FAILED", "CANCELLED"}:
            self.remove(project_root, project_id, run_id)
            return "removed"
        if stage == "COMPLETED" and self._cleanup_completed:
            self.remove(project_root, project_id, run_id)
            return "removed"
        return "kept"

    def sweep(
        self,
        projects: Mapping[str, Path],
        stage_of: Callable[[str], str | None],
    ) -> list[str]:
        """Removes orphaned worktrees across the given git projects.

        ``stage_of(run_id)`` returns the run's terminal stage
        (COMPLETED / FAILED / CANCELLED), ``"ACTIVE"`` for a live run,
        or None when the run store does not know the run. Orphans are
        unknown runs and runs that ended FAILED/CANCELLED (same policy
        as :meth:`finish`). Returns a description per removal.
        """
        removed: list[str] = []
        for project_id, project_root in projects.items():
            base = self._root / project_id
            if not base.is_dir() or not self.is_git_repo(project_root):
                continue
            try:
                run_git(project_root, "worktree", "prune")
            except WorktreeError:
                pass
            for child in sorted(base.iterdir()):
                if not child.is_dir() or not _RUN_ID_PATTERN.match(child.name):
                    continue
                stage = stage_of(child.name)
                if stage == "COMPLETED" and not self._cleanup_completed:
                    continue
                if stage == "ACTIVE":
                    continue
                if self.remove(project_root, project_id, child.name):
                    removed.append(
                        f"{project_id}/{child.name} "
                        f"({'unknown run' if stage is None else stage.lower()})",
                    )
        if removed:
            logger.info(
                "Startup sweep removed %d orphaned worktree(s): %s",
                len(removed), ", ".join(removed),
            )
        return removed
