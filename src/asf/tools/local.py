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
running them yourself in a terminal. The command *environment* is
nevertheless kept minimal on purpose (see :func:`build_sandbox_env`):
test commands execute code an LLM wrote, and the backend's own
environment carries its secrets (hosting tokens, model API keys, the
run-database password — all under the ``ASF_`` prefix, which is never
passed through).

Project profile keys (under ``configuration``) that shape command
execution for local projects:

- ``testEnv``: map of extra environment variables for test commands.
  Values are literal strings or ``{"env": NAME}`` references resolved
  from the backend's environment by the assembly (the config
  convention for secrets). ``ASF_``-prefixed names are refused.
- ``testEnvAllowlist``: list of variable names to inherit from the
  backend environment (toolchain locations such as ``JAVA_HOME`` or
  ``NODE_PATH``). ``ASF_``-prefixed names are refused here too.
- ``sandboxLimits``: optional POSIX resource limits for test
  commands — ``cpuSeconds``, ``memoryBytes``, ``maxProcesses``
  (applied with ``setrlimit``; unset keys mean no limit).

Projects opt in individually through ``repository.path`` in their
profile. :class:`LocalWorkspace` holds the project-id → folder mapping
plus the *per-execution* binding (a :class:`contextvars.ContextVar`,
so parallel runs of different projects each see their own folder) and
a lock per project (so two runs of the SAME project never execute
code agents against its folder at the same time), and
:class:`WorkspaceRepository` / :class:`WorkspaceSandbox`
route each port call to the bound project's folder, delegating to a
fallback implementation for projects without one.
"""

from __future__ import annotations

import contextvars
import os
import re
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath

from asf.tools.changeset import ChangeSet
from asf.tools.ports import (
    CommandResult,
    CommandSpec,
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
    "SandboxResourceLimits",
    "SandboxSettings",
    "WorkspaceRepository",
    "WorkspaceSandbox",
    "build_sandbox_env",
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


# ---------------------------------------------------------------------------
# Sandbox environment
# ---------------------------------------------------------------------------

_ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Always inherited (when present): enough for shells and toolchains to
# locate themselves and agree on encodings/temp space.
_BASE_ENV_NAMES = frozenset({"PATH", "LANG", "LC_ALL", "TMPDIR"})
# Without these, many Windows tools (including Python itself in some
# install layouts) cannot start at all.
_WINDOWS_ENV_NAMES = frozenset({"SYSTEMROOT", "COMSPEC", "TEMP", "TMP", "PATHEXT"})

# Grace period between asking a timed-out process tree to stop and
# force-killing it.
_TERMINATE_GRACE_SECONDS = 3.0


def build_sandbox_env(
    base: Mapping[str, str],
    allowlist: Sequence[str],
    extra: Mapping[str, str],
    *,
    home: str,
) -> dict[str, str]:
    """Builds the minimal environment a sandbox command runs with.

    Pure: the result depends only on the arguments (and the platform's
    name rules). Policy:

    - From ``base`` keep only PATH, LANG, LC_ALL, TMPDIR (plus the
      Windows startup essentials on Windows) and the names in
      ``allowlist`` — matching is case-insensitive because Windows
      variable names are.
    - ``extra`` (the project's declared ``testEnv``) is applied last
      and wins over inherited values.
    - NOTHING whose name starts with ``ASF_`` is ever passed, from
      any source: that prefix carries the backend's own secrets, and
      test commands run LLM-written code.
    - ``HOME`` (and ``USERPROFILE`` on Windows) points at ``home`` —
      a fresh per-run temporary directory — never the user's real
      home; ``TMPDIR`` defaults to it when the base has none.
    """
    wanted = set(_BASE_ENV_NAMES)
    if os.name == "nt":
        wanted |= _WINDOWS_ENV_NAMES
    for name in allowlist:
        if not _ENV_NAME_PATTERN.match(name):
            raise ValueError(f"Invalid environment variable name in allowlist: {name!r}")
        wanted.add(name.upper())
    env: dict[str, str] = {}
    for key, value in base.items():
        upper = key.upper()
        if upper.startswith("ASF_"):
            continue
        if upper in wanted:
            env[key] = value
    for key, value in extra.items():
        if not _ENV_NAME_PATTERN.match(key):
            raise ValueError(f"Invalid environment variable name in testEnv: {key!r}")
        if key.upper().startswith("ASF_"):
            continue
        for existing in [k for k in env if k.upper() == key.upper()]:
            del env[existing]
        env[key] = value
    env["HOME"] = home
    if os.name == "nt":
        env["USERPROFILE"] = home
    env.setdefault("TMPDIR", home)
    return env


@dataclass(frozen=True)
class SandboxResourceLimits:
    """Optional POSIX rlimits for sandbox commands (None = no limit)."""

    cpu_seconds: int | None = None
    memory_bytes: int | None = None
    max_processes: int | None = None


@dataclass(frozen=True)
class SandboxSettings:
    """Per-project command-execution settings for LocalSandbox."""

    env_allowlist: tuple[str, ...] = ()
    env_extra: Mapping[str, str] = field(default_factory=dict)
    resource_limits: SandboxResourceLimits | None = None


class _CappedReader(threading.Thread):
    """Drains one pipe, keeping only the first ``limit`` bytes.

    The stream is always read to EOF — stopping early would leave the
    writer blocked on a full pipe — but bytes beyond the cap are
    counted and discarded, never buffered.
    """

    def __init__(self, stream: object, limit: int) -> None:
        super().__init__(daemon=True)
        self._stream = stream
        self._limit = limit
        self.buffer = bytearray()
        self.truncated = False

    def run(self) -> None:
        try:
            while True:
                chunk = os.read(self._stream.fileno(), 65_536)  # type: ignore[attr-defined]
                if not chunk:
                    break
                room = self._limit - len(self.buffer)
                if room > 0:
                    self.buffer += chunk[:room]
                if len(chunk) > max(room, 0):
                    self.truncated = True
        except OSError:
            pass
        finally:
            try:
                self._stream.close()  # type: ignore[attr-defined]
            except Exception:
                pass


def _terminate_tree(process: subprocess.Popen) -> None:
    """Stops a timed-out command and every process it spawned.

    POSIX: the command runs in its own session, so the whole process
    group gets SIGTERM, a grace period, then SIGKILL. Windows: the
    command runs in a new process group and ``taskkill /T`` walks the
    tree (plain first, forced after the same grace period).
    """
    if os.name == "nt":
        _taskkill(process.pid, force=False)
        try:
            process.wait(timeout=_TERMINATE_GRACE_SECONDS)
            return
        except subprocess.TimeoutExpired:
            pass
        _taskkill(process.pid, force=True)
        try:
            process.wait(timeout=_TERMINATE_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        return
    try:
        pgid: int | None = os.getpgid(process.pid)
    except (ProcessLookupError, PermissionError):
        pgid = None
    if pgid is not None:
        try:
            os.killpg(pgid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
    try:
        process.wait(timeout=_TERMINATE_GRACE_SECONDS)
        return
    except subprocess.TimeoutExpired:
        pass
    if pgid is not None:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    try:
        process.wait(timeout=_TERMINATE_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _taskkill(pid: int, *, force: bool) -> None:
    args = ["taskkill", "/PID", str(pid), "/T"]
    if force:
        args.append("/F")
    try:
        subprocess.run(args, capture_output=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        pass  # already gone, or taskkill itself unavailable: wait() decides


def _rlimit_preexec(limits: SandboxResourceLimits):  # noqa: ANN202
    """Builds a preexec_fn applying the configured POSIX rlimits."""
    def apply() -> None:
        import resource

        if limits.cpu_seconds is not None:
            resource.setrlimit(
                resource.RLIMIT_CPU, (limits.cpu_seconds, limits.cpu_seconds),
            )
        if limits.memory_bytes is not None:
            resource.setrlimit(
                resource.RLIMIT_AS, (limits.memory_bytes, limits.memory_bytes),
            )
        if limits.max_processes is not None:
            resource.setrlimit(
                resource.RLIMIT_NPROC,
                (limits.max_processes, limits.max_processes),
            )

    return apply


def _validate_argv0(argv0: str, root: Path, spec: CommandSpec) -> None:
    """Refuses a relative-path argv[0] that escapes the project folder.

    Bare command names (``python``, ``pytest``) resolve through PATH
    and absolute paths are the operator's explicit choice; only a
    relative path — the shape an LLM-written test command could use
    to reach outside the workspace — is constrained to the folder.
    """
    if not argv0:
        raise SandboxError("Command argv must not be empty", command=spec)
    if "/" not in argv0 and "\\" not in argv0:
        return
    if PurePosixPath(argv0).is_absolute() or PureWindowsPath(argv0).is_absolute():
        return
    try:
        _resolve_within(root, argv0.replace("\\", "/"))
    except RepositoryError as error:
        raise SandboxError(str(error), command=spec) from None


class LocalSandbox:
    """SandboxPort that applies change sets to the project folder itself
    and runs the commands there. See the module docstring for the trust
    model — this is a local workspace, not an isolation sandbox.

    Commands run with a minimal environment (see
    :func:`build_sandbox_env`), in their own process group/session so
    a timeout kills the whole tree, and with stdout/stderr streamed
    through capped readers so a runaway command cannot fill memory.
    A timed-out command yields a ``CommandResult`` with
    ``timed_out=True`` (its tree already killed) instead of raising.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        settings: SandboxSettings | None = None,
        base_env: Mapping[str, str] | None = None,
    ) -> None:
        self._root = Path(root)
        self._settings = settings or SandboxSettings()
        self._base_env = base_env

    def run(
        self, commands: Sequence[CommandSpec], changes: ChangeSet, ref: str
    ) -> SandboxResult:
        self._apply(changes)
        # One fresh home per run() call: tools that cache into $HOME
        # cannot leak state (or read the real home) across runs.
        with tempfile.TemporaryDirectory(prefix="asf-sandbox-") as home:
            env = build_sandbox_env(
                self._base_env if self._base_env is not None else os.environ,
                self._settings.env_allowlist,
                self._settings.env_extra,
                home=home,
            )
            outcomes = [self._run_one(spec, env) for spec in commands]
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

    def _run_one(self, spec: CommandSpec, env: Mapping[str, str]) -> CommandResult:
        argv = list(spec.argv)
        if not argv:
            raise SandboxError("Command argv must not be empty", command=spec)
        _validate_argv0(argv[0], self._root, spec)
        started = time.monotonic()
        try:
            process = subprocess.Popen(
                argv,
                cwd=self._root,
                env=dict(env),
                shell=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                **self._spawn_kwargs(),
            )
        except OSError as error:
            raise SandboxError(
                f"Could not run command {spec.argv!r}: {error}", command=spec,
            ) from None
        assert process.stdout is not None and process.stderr is not None
        readers = [
            _CappedReader(process.stdout, spec.output_limit_bytes),
            _CappedReader(process.stderr, spec.output_limit_bytes),
        ]
        for reader in readers:
            reader.start()
        timed_out = False
        try:
            process.wait(timeout=spec.timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            _terminate_tree(process)
        # Readers end at EOF; a detached grandchild can hold a pipe
        # open past the main process's exit, so joins are bounded and
        # the result is built from whatever was captured by then.
        for reader in readers:
            reader.join(timeout=5)
        duration_ms = int((time.monotonic() - started) * 1000)
        return CommandResult(
            exit_code=process.returncode if process.returncode is not None else -1,
            stdout=bytes(readers[0].buffer).decode("utf-8", errors="replace"),
            stderr=bytes(readers[1].buffer).decode("utf-8", errors="replace"),
            duration_ms=duration_ms,
            timed_out=timed_out,
            stdout_truncated=readers[0].truncated,
            stderr_truncated=readers[1].truncated,
        )

    def _spawn_kwargs(self) -> dict:
        if os.name == "nt":
            # The constant exists only on Windows builds; getattr
            # keeps type checkers on other platforms quiet.
            return {
                "creationflags": getattr(
                    subprocess, "CREATE_NEW_PROCESS_GROUP", 0,
                ),
            }
        kwargs: dict = {"start_new_session": True}
        limits = self._settings.resource_limits
        if limits is not None:
            kwargs["preexec_fn"] = _rlimit_preexec(limits)
        return kwargs


class LocalWorkspace:
    """Project-id → folder mapping plus the per-execution binding.

    The port calls carry no project id, so the assembly binds the
    workspace to the project of the step being executed. The binding
    lives in a :class:`contextvars.ContextVar`: each drive — whatever
    thread or context runs it — sees only its own binding, so two
    runs of different projects executing in parallel can never read
    or write each other's folders. (The binding used to be one shared
    attribute; with one drive thread per run that was a cross-project
    data-corruption race.) Callers must reset the token returned by
    :meth:`bind` when the step finishes.

    A per-project lock additionally serializes code-agent execution
    for projects that share one folder: two runs of the same project
    must never apply change sets or run test commands against the
    same working tree at the same time.
    """

    def __init__(
        self,
        roots: Mapping[str, str | Path] | None = None,
        sandbox_settings: Mapping[str, SandboxSettings] | None = None,
    ) -> None:
        self._roots: dict[str, Path] = {}
        for project_id, path in (roots or {}).items():
            self.set_root(project_id, path)
        self._sandbox_settings: dict[str, SandboxSettings] = dict(
            sandbox_settings or {},
        )
        self._bound: contextvars.ContextVar[str | None] = contextvars.ContextVar(
            "asf-local-workspace-project", default=None,
        )
        self._locks_guard = threading.Lock()
        self._project_locks: dict[str, threading.Lock] = {}

    def set_sandbox_settings(
        self, project_id: str, settings: SandboxSettings | None,
    ) -> None:
        if settings is None:
            self._sandbox_settings.pop(project_id, None)
        else:
            self._sandbox_settings[project_id] = settings

    def current_sandbox_settings(self) -> SandboxSettings | None:
        project_id = self._bound.get()
        if project_id is None:
            return None
        return self._sandbox_settings.get(project_id)

    def set_root(self, project_id: str, path: str | Path | None) -> None:
        if path is None or (isinstance(path, str) and not path.strip()):
            self._roots.pop(project_id, None)
        else:
            self._roots[project_id] = Path(path)

    def remove(self, project_id: str) -> None:
        self._roots.pop(project_id, None)
        self._sandbox_settings.pop(project_id, None)
        with self._locks_guard:
            self._project_locks.pop(project_id, None)

    def has_local_root(self, project_id: str) -> bool:
        return project_id in self._roots

    def bind(self, project_id: str) -> contextvars.Token[str | None]:
        """Binds this execution context to a project; reset the token."""
        return self._bound.set(project_id)

    def reset_binding(self, token: contextvars.Token[str | None]) -> None:
        self._bound.reset(token)

    def bound_project(self) -> str | None:
        return self._bound.get()

    def current_root(self) -> Path | None:
        project_id = self._bound.get()
        if project_id is None:
            return None
        return self._roots.get(project_id)

    def project_lock(self, project_id: str) -> threading.Lock:
        """The lock serializing code-agent work for one project."""
        with self._locks_guard:
            lock = self._project_locks.get(project_id)
            if lock is None:
                lock = threading.Lock()
                self._project_locks[project_id] = lock
            return lock


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
            LocalSandbox(
                root, settings=self._workspace.current_sandbox_settings(),
            )
            if root is not None else self._fallback
        )
        return delegate.run(commands, changes, ref)
