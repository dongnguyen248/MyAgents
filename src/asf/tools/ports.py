from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from asf.tools.changeset import ChangeSet

__all__ = [
    "CommandSpec",
    "CommandResult",
    "SandboxResult",
    "RepositoryPort",
    "SandboxPort",
    "RepositoryError",
    "FileTooLargeError",
    "FileNotFoundInRepository",
    "SandboxError",
    "CommandTimeoutError",
]


@dataclass(frozen=True)
class CommandSpec:
    """Specification for a single command to run in the sandbox."""

    argv: tuple[str, ...]
    timeout_seconds: int = 120
    output_limit_bytes: int = 64_000


@dataclass(frozen=True)
class CommandResult:
    """Result of a single command execution."""

    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    # True when the command never ran: an earlier command failed
    # and the sandbox was in fail-fast mode. exit_code is -1 then.
    skipped: bool = False


@dataclass(frozen=True)
class AppliedRelabel:
    """A change whose operation label was rewritten while applying it."""

    path: str
    from_operation: str
    to_operation: str


@dataclass(frozen=True)
class SandboxResult:
    """Aggregate result of running multiple commands in a sandbox."""

    commands: tuple[CommandResult, ...]
    relabels: tuple[AppliedRelabel, ...] = ()


class RepositoryError(Exception):
    """Base exception for repository port errors."""

    def __init__(self, message: str, *, path: str | None = None, ref: str | None = None) -> None:
        super().__init__(message)
        self.path = path
        self.ref = ref


class FileTooLargeError(RepositoryError):
    """Raised when a file exceeds the maximum allowed size for reading."""

    def __init__(self, path: str, ref: str, max_bytes: int) -> None:
        super().__init__(
            f"File '{path}' at ref '{ref}' exceeds maximum size of {max_bytes} bytes",
            path=path,
            ref=ref,
        )
        self.max_bytes = max_bytes


class FileNotFoundInRepository(RepositoryError):
    """Raised when a file does not exist at the given ref."""

    def __init__(self, path: str, ref: str) -> None:
        super().__init__(
            f"File '{path}' not found at ref '{ref}'",
            path=path,
            ref=ref,
        )


@dataclass(frozen=True)
class SandboxFailure:
    """Where and how a sandbox operation failed: the cause chain that
    travels with a SandboxError instead of being flattened away.

    Only the command NAME (argv[0]) is ever recorded — never the full
    argv, which may carry secrets in its arguments.
    """

    phase: str
    exception_type: str
    command_name: str | None = None
    cwd: Path | None = None
    errno: int | None = None
    elapsed_ms: int | None = None

    def details(self) -> dict[str, Any]:
        """The flat, JSON-safe details dict for an agent error."""
        details: dict[str, Any] = {
            "phase": self.phase,
            "exceptionType": self.exception_type,
        }
        if self.errno is not None:
            details["errno"] = self.errno
        if self.command_name is not None:
            details["commandName"] = self.command_name
        if self.cwd is not None:
            details["cwd"] = str(self.cwd)
            details["cwdExists"] = self.cwd.is_dir()
        if self.elapsed_ms is not None:
            details["elapsedMs"] = self.elapsed_ms
        return details


class SandboxError(Exception):
    """Base exception for sandbox port errors."""

    def __init__(
        self,
        message: str,
        *,
        command: CommandSpec | None = None,
        details: dict[str, Any] | None = None,
        failure: SandboxFailure | None = None,
    ) -> None:
        super().__init__(message)
        self.command = command
        if details is not None:
            self.details: dict[str, Any] = dict(details)
        elif failure is not None:
            self.details = failure.details()
        else:
            self.details = {}


def missing_working_directory(root: Path, command: CommandSpec) -> SandboxError:
    """The spawn working directory is gone — a distinct start failure."""
    name = command.argv[0] if command.argv else None
    return SandboxError(
        f"Working directory does not exist: {root} "
        "(it may have been moved or removed; one possible cause is "
        "antivirus software)",
        command=command,
        failure=SandboxFailure("start", "SandboxError", command_name=name, cwd=root, elapsed_ms=0),
    )


def spawn_failure(
    error: OSError, command: CommandSpec, root: Path, elapsed_ms: int
) -> SandboxError:
    """A process that could not be started, with the OS cause attached."""
    name = command.argv[0] if command.argv else ""
    return SandboxError(
        f"Could not run command {name!r}: {error}",
        command=command,
        failure=SandboxFailure(
            "start",
            type(error).__name__,
            command_name=name or None,
            cwd=root,
            errno=error.errno,
            elapsed_ms=elapsed_ms,
        ),
    )


def capture_failure(command: CommandSpec, root: Path, elapsed_ms: int) -> SandboxError:
    """A started process whose output pipes could not be read."""
    name = command.argv[0] if command.argv else ""
    return SandboxError(
        f"Could not capture output of {name!r}",
        command=command,
        failure=SandboxFailure(
            "collect",
            "SandboxError",
            command_name=name or None,
            cwd=root,
            elapsed_ms=elapsed_ms,
        ),
    )


class SandboxApplyError(SandboxError):
    """A change set failed validation against the working tree.

    Deterministic: the same change set against the same tree fails
    identically on every retry, so agents report it under a
    non-retryable code instead of SANDBOX_ERROR.
    """


class CommandTimeoutError(SandboxError):
    """Raised when a command exceeds its timeout."""

    def __init__(self, command: CommandSpec) -> None:
        name = command.argv[0] if command.argv else ""
        super().__init__(
            f"Command timed out after {command.timeout_seconds}s: {name}",
            command=command,
            failure=SandboxFailure(
                "run",
                "CommandTimeoutError",
                command_name=name or None,
                elapsed_ms=command.timeout_seconds * 1000,
            ),
        )


class RepositoryPort(Protocol):
    """Read-only port for accessing repository files at a given ref."""

    def list_tree(self, ref: str, prefix: str = "") -> tuple[str, ...]:
        """List all file paths under prefix at the given ref."""
        ...

    def read_file(self, path: str, ref: str, max_bytes: int = 256_000) -> str:
        """Read a file's content at the given ref, up to max_bytes.

        Raises:
            FileNotFoundInRepository: if the file does not exist.
            FileTooLargeError: if the file exceeds max_bytes.
        """
        ...


class SandboxPort(Protocol):
    """Port for running commands in an ephemeral sandbox with a change set applied."""

    def run(
        self,
        commands: Sequence[CommandSpec],
        changes: ChangeSet,
        ref: str,
        *,
        fail_fast: bool = True,
    ) -> SandboxResult:
        """Create a workspace at ref, apply changes, run commands, return results.

        With ``fail_fast`` (the default), commands after the first
        failure are not executed: their results are marked
        ``skipped`` so the result list always lines up with the
        command list.

        A command that exceeds its timeout is reported either by
        raising :class:`CommandTimeoutError` or by a
        :class:`CommandResult` with ``timed_out=True`` for that
        command (adapters that can clean up the process tree report
        the result; callers must handle both shapes).

        Raises:
            SandboxError: on sandbox infrastructure failure.
            CommandTimeoutError: if any command exceeds its timeout.
        """
        ...
