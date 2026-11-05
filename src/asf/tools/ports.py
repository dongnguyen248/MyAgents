from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

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
class SandboxResult:
    """Aggregate result of running multiple commands in a sandbox."""

    commands: tuple[CommandResult, ...]


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


class SandboxError(Exception):
    """Base exception for sandbox port errors."""

    def __init__(self, message: str, *, command: CommandSpec | None = None) -> None:
        super().__init__(message)
        self.command = command


class CommandTimeoutError(SandboxError):
    """Raised when a command exceeds its timeout."""

    def __init__(self, command: CommandSpec) -> None:
        super().__init__(
            f"Command timed out after {command.timeout_seconds}s: {command.argv}",
            command=command,
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
