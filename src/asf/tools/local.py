"""Local-filesystem implementations of the repository and sandbox ports.

These adapters bind the code agents to a real project folder on the
machine running the platform:

- :class:`LocalRepository` serves ``RepositoryPort`` reads from the
  folder, so the implementation/fix agents see the project's actual
  files when they build their prompts.
- :class:`LocalSandbox` serves ``SandboxPort`` by applying a change set
  to the folder itself and running the commands there for real, so the
  test agent's verdict comes from actual command exit codes.

A ``ref`` means "the current working tree"; there is one tree per
folder, so the ref value is accepted and ignored.

Trust model: this is a *local, trusted* sandbox, not an isolation
boundary. Commands run with the platform user's privileges inside the
project folder, and change sets are written to that folder. Only point
it at projects whose configured test commands you trust, exactly like
running them yourself in a terminal.

Projects opt in individually through ``repository.path`` in their
profile. :class:`LocalWorkspace` holds the project-id → folder mapping
plus the currently bound project (runs are driven one at a time by the
local worker), and :class:`WorkspaceRepository` / :class:`WorkspaceSandbox`
route each port call to the bound project's folder, delegating to a
fallback implementation for projects without one.
"""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath, PureWindowsPath

from asf.tools.changeset import ChangeSet
from asf.tools.ports import (
    CommandResult,
    CommandSpec,
    CommandTimeoutError,
    FileNotFoundInRepository,
    FileTooLargeError,
    RepositoryError,
    RepositoryPort,
    SandboxError,
    SandboxPort,
    SandboxResult,
)

__all__ = [
    "LocalRepository",
    "LocalSandbox",
    "LocalWorkspace",
    "WorkspaceRepository",
    "WorkspaceSandbox",
]

_IGNORED_DIRS = frozenset({
    ".git", ".hg", ".svn", ".venv", "venv", "__pycache__",
    "node_modules", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "dist", "build",
})


def _resolve_within(root: Path, path: str) -> Path:
    """Resolve a repository-relative path, refusing anything outside root."""
    if (
        not path
        or PurePosixPath(path).is_absolute()
        or PureWindowsPath(path).is_absolute()
        or PureWindowsPath(path).drive
    ):
        raise RepositoryError(f"Path must be relative: {path!r}", path=path)
    resolved_root = root.resolve()
    candidate = (resolved_root / Path(*PurePosixPath(path).parts)).resolve()
    if not candidate.is_relative_to(resolved_root):
        raise RepositoryError(f"Path escapes the project folder: {path!r}", path=path)
    return candidate


class LocalRepository:
    """RepositoryPort over one real project folder (the working tree)."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    def list_tree(self, ref: str, prefix: str = "") -> tuple[str, ...]:
        if not self._root.is_dir():
            return ()
        paths: list[str] = []
        for dirpath, dirnames, filenames in os.walk(self._root):
            dirnames[:] = sorted(d for d in dirnames if d not in _IGNORED_DIRS)
            for name in sorted(filenames):
                relative = (Path(dirpath) / name).relative_to(self._root).as_posix()
                if not prefix or relative.startswith(prefix):
                    paths.append(relative)
        return tuple(sorted(paths))

    def read_file(self, path: str, ref: str, max_bytes: int = 256_000) -> str:
        target = _resolve_within(self._root, path)
        if not target.is_file():
            raise FileNotFoundInRepository(path, ref)
        if target.stat().st_size > max_bytes:
            raise FileTooLargeError(path, ref, max_bytes=max_bytes)
        try:
            return target.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            raise RepositoryError(
                f"File '{path}' is not valid UTF-8 text", path=path, ref=ref,
            ) from None


class LocalSandbox:
    """SandboxPort that applies change sets to the project folder itself
    and runs the commands there. See the module docstring for the trust
    model — this is a local workspace, not an isolation sandbox."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    def run(
        self, commands: Sequence[CommandSpec], changes: ChangeSet, ref: str
    ) -> SandboxResult:
        self._apply(changes)
        outcomes: list[CommandResult] = []
        for spec in commands:
            outcomes.append(self._run_one(spec))
        return SandboxResult(commands=tuple(outcomes))

    def _apply(self, changes: ChangeSet) -> None:
        # Validate the whole change set against the current tree first, so
        # a bad change set leaves the folder untouched (mirrors the
        # in-memory sandbox's create/modify/delete rules).
        targets: list[tuple[Path, str, str | None]] = []
        for change in changes.changes:
            try:
                target = _resolve_within(self._root, change.path)
            except RepositoryError as error:
                raise SandboxError(str(error), command=None) from None
            exists = target.is_file()
            if change.operation == "create" and exists:
                raise SandboxError(
                    f"Cannot create existing file: {change.path}", command=None,
                )
            if change.operation in ("modify", "delete") and not exists:
                raise SandboxError(
                    f"Cannot {change.operation} missing file: {change.path}",
                    command=None,
                )
            targets.append((target, change.operation, change.content))
        for target, operation, content in targets:
            if operation == "delete":
                target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((content or "").encode("utf-8"))

    def _run_one(self, spec: CommandSpec) -> CommandResult:
        started = time.monotonic()
        try:
            completed = subprocess.run(
                list(spec.argv),
                cwd=self._root,
                capture_output=True,
                timeout=spec.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise CommandTimeoutError(spec) from None
        except OSError as error:
            raise SandboxError(
                f"Could not run command {spec.argv!r}: {error}", command=spec,
            ) from None
        duration_ms = int((time.monotonic() - started) * 1000)
        return CommandResult(
            exit_code=completed.returncode,
            stdout=_truncate(completed.stdout, spec.output_limit_bytes),
            stderr=_truncate(completed.stderr, spec.output_limit_bytes),
            duration_ms=duration_ms,
        )


def _truncate(data: bytes, limit: int) -> str:
    return data[:limit].decode("utf-8", errors="replace")


class LocalWorkspace:
    """Project-id → folder mapping plus the currently bound project.

    The port calls carry no project id, so the assembly binds the
    workspace to the project of the run being executed (the local worker
    drives one step at a time) and the routed ports below resolve the
    folder per call.
    """

    def __init__(self, roots: Mapping[str, str | Path] | None = None) -> None:
        self._roots: dict[str, Path] = {}
        for project_id, path in (roots or {}).items():
            self.set_root(project_id, path)
        self._current: str | None = None

    def set_root(self, project_id: str, path: str | Path | None) -> None:
        if path is None or (isinstance(path, str) and not path.strip()):
            self._roots.pop(project_id, None)
        else:
            self._roots[project_id] = Path(path)

    def remove(self, project_id: str) -> None:
        self._roots.pop(project_id, None)
        if self._current == project_id:
            self._current = None

    def bind(self, project_id: str) -> None:
        self._current = project_id

    def current_root(self) -> Path | None:
        if self._current is None:
            return None
        return self._roots.get(self._current)


class WorkspaceRepository:
    """RepositoryPort routed by the bound project's local folder.

    Projects without a configured folder delegate to the fallback
    repository, so local and non-local projects can share one registry.
    """

    def __init__(self, workspace: LocalWorkspace, fallback: RepositoryPort) -> None:
        self._workspace = workspace
        self._fallback = fallback

    def _delegate(self) -> RepositoryPort:
        root = self._workspace.current_root()
        return LocalRepository(root) if root is not None else self._fallback

    def list_tree(self, ref: str, prefix: str = "") -> tuple[str, ...]:
        return self._delegate().list_tree(ref, prefix)

    def read_file(self, path: str, ref: str, max_bytes: int = 256_000) -> str:
        return self._delegate().read_file(path, ref, max_bytes)


class WorkspaceSandbox:
    """SandboxPort routed by the bound project's local folder."""

    def __init__(self, workspace: LocalWorkspace, fallback: SandboxPort) -> None:
        self._workspace = workspace
        self._fallback = fallback

    def run(
        self, commands: Sequence[CommandSpec], changes: ChangeSet, ref: str
    ) -> SandboxResult:
        root = self._workspace.current_root()
        delegate: SandboxPort = (
            LocalSandbox(root) if root is not None else self._fallback
        )
        return delegate.run(commands, changes, ref)
