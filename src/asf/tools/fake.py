from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from asf.tools.changeset import ChangeSet
from asf.tools.ports import (
    CommandResult,
    CommandSpec,
    CommandTimeoutError,
    FileNotFoundInRepository,
    FileTooLargeError,
    SandboxError,
    SandboxResult,
)

__all__ = [
    "InMemoryRepository",
    "ScriptedSandbox",
    "InMemorySandbox",
]


@dataclass(frozen=True)
class _FileTree:
    """Immutable file tree for a single ref."""

    files: Mapping[str, str] = field(default_factory=dict)

    def __contains__(self, path: str) -> bool:
        return path in self.files

    def get(self, path: str, max_bytes: int) -> str:
        content = self.files.get(path)
        if content is None:
            raise FileNotFoundInRepository(path, ref="")
        if len(content.encode("utf-8")) > max_bytes:
            raise FileTooLargeError(path, ref="", max_bytes=max_bytes)
        return content


class InMemoryRepository:
    """In-memory implementation of RepositoryPort for testing.

    Stores a dict of ref -> file tree. Each file tree is a dict of path -> content.
    """

    def __init__(self, trees: Mapping[str, Mapping[str, str]] | None = None) -> None:
        self._trees: dict[str, _FileTree] = {
            ref: _FileTree(dict(files)) for ref, files in (trees or {}).items()
        }

    def add_tree(self, ref: str, files: Mapping[str, str]) -> None:
        """Add or replace a file tree for a ref."""
        self._trees[ref] = _FileTree(dict(files))

    def list_tree(self, ref: str, prefix: str = "") -> tuple[str, ...]:
        tree = self._trees.get(ref)
        if tree is None:
            return ()
        if not prefix:
            return tuple(sorted(tree.files.keys()))
        return tuple(sorted(p for p in tree.files.keys() if p.startswith(prefix)))

    def read_file(self, path: str, ref: str, max_bytes: int = 256_000) -> str:
        tree = self._trees.get(ref)
        if tree is None:
            raise FileNotFoundInRepository(path, ref)
        return tree.get(path, max_bytes)


class ScriptedSandbox:
    """Sandbox that returns pre-recorded results for specific command signatures."""

    def __init__(
        self,
        results: Mapping[tuple[str, ...], CommandResult] | None = None,
        default_result: CommandResult | None = None,
        timeout_commands: set[tuple[str, ...]] | None = None,
    ) -> None:
        self._results = dict(results or {})
        self._default_result = default_result or CommandResult(
            exit_code=0, stdout="", stderr="", duration_ms=1
        )
        self._timeout_commands = timeout_commands or set()

    def record(self, argv: Sequence[str], result: CommandResult) -> None:
        self._results[tuple(argv)] = result

    def set_timeout(self, argv: Sequence[str]) -> None:
        self._timeout_commands.add(tuple(argv))

    def run(
        self, commands: Sequence[CommandSpec], changes: ChangeSet, ref: str
    ) -> SandboxResult:
        outcomes: list[CommandResult] = []
        for cmd in commands:
            argv_key = tuple(cmd.argv)
            if argv_key in self._timeout_commands:
                raise CommandTimeoutError(cmd)
            result = self._results.get(argv_key, self._default_result)
            outcomes.append(result)
        return SandboxResult(commands=tuple(outcomes))


class InMemorySandbox:
    """Sandbox that applies the ChangeSet to an in-memory file tree and runs commands."""

    def __init__(
        self,
        repository: InMemoryRepository,
        command_results: Mapping[tuple[str, ...], CommandResult] | None = None,
    ) -> None:
        self._repository = repository
        self._command_results = dict(command_results or {})
        self._default_result = CommandResult(
            exit_code=0, stdout="", stderr="", duration_ms=1
        )

    def set_command_result(self, argv: Sequence[str], result: CommandResult) -> None:
        self._command_results[tuple(argv)] = result

    def run(
        self, commands: Sequence[CommandSpec], changes: ChangeSet, ref: str
    ) -> SandboxResult:
        # Copy the file tree at ref
        tree = self._repository._trees.get(ref)
        if tree is None:
            working_files: dict[str, str] = {}
        else:
            working_files = dict(tree.files)

        # Apply the ChangeSet
        for fc in changes.changes:
            if fc.operation == "create":
                if fc.path in working_files:
                    raise SandboxError(f"Cannot create existing file: {fc.path}", command=None)
                if fc.content is None:
                    raise SandboxError("create operation requires content", command=None)
                working_files[fc.path] = fc.content
            elif fc.operation == "modify":
                if fc.path not in working_files:
                    raise SandboxError(f"Cannot modify missing file: {fc.path}", command=None)
                if fc.content is None:
                    raise SandboxError("modify operation requires content", command=None)
                working_files[fc.path] = fc.content
            elif fc.operation == "delete":
                if fc.path not in working_files:
                    raise SandboxError(f"Cannot delete missing file: {fc.path}", command=None)
                del working_files[fc.path]

        # Run commands (simulated - just returns recorded results)
        outcomes: list[CommandResult] = []
        for cmd in commands:
            argv_key = tuple(cmd.argv)
            result = self._command_results.get(argv_key, self._default_result)
            outcomes.append(result)

        return SandboxResult(commands=tuple(outcomes))