"""Local filesystem repository/sandbox adapters (tools.local)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from asf.tools.changeset import ChangeSet, FileChange
from asf.tools.fake import InMemoryRepository, ScriptedSandbox
from asf.tools.local import (
    LocalRepository,
    LocalSandbox,
    LocalWorkspace,
    WorkspaceRepository,
    WorkspaceSandbox,
)
from asf.tools.ports import (
    CommandResult,
    CommandSpec,
    CommandTimeoutError,
    FileNotFoundInRepository,
    FileTooLargeError,
    RepositoryError,
    SandboxError,
)


def _write(root: Path, relative: str, content: str) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def _changeset(*changes: FileChange) -> ChangeSet:
    return ChangeSet(changes=list(changes))


PYTHON = sys.executable


def test_local_repository_reads_and_lists(tmp_path: Path):
    _write(tmp_path, "src/app.py", "print('hi')\n")
    _write(tmp_path, "README.md", "# demo\n")
    _write(tmp_path, ".git/config", "ignored")
    repository = LocalRepository(tmp_path)
    assert repository.read_file("src/app.py", "main") == "print('hi')\n"
    assert repository.list_tree("main") == ("README.md", "src/app.py")
    assert repository.list_tree("main", prefix="src/") == ("src/app.py",)


def test_local_repository_errors(tmp_path: Path):
    repository = LocalRepository(tmp_path)
    with pytest.raises(FileNotFoundInRepository):
        repository.read_file("missing.py", "main")
    _write(tmp_path, "big.txt", "x" * 100)
    with pytest.raises(FileTooLargeError):
        repository.read_file("big.txt", "main", max_bytes=10)
    for bad in ("../outside.txt", "/abs/path.txt", "..\\win.txt"):
        with pytest.raises(RepositoryError):
            repository.read_file(bad, "main")


def test_local_sandbox_applies_changeset_and_runs_commands(tmp_path: Path):
    _write(tmp_path, "keep.py", "VALUE = 1\n")
    sandbox = LocalSandbox(tmp_path)
    changes = _changeset(
        FileChange(path="pkg/mod.py", operation="create", content="VALUE = 42\n"),
        FileChange(path="keep.py", operation="modify", content="VALUE = 2\n"),
    )
    result = sandbox.run(
        [CommandSpec(argv=(PYTHON, "-c", "import pkg.mod; print(pkg.mod.VALUE)"))],
        changes,
        "main",
    )
    assert (tmp_path / "pkg" / "mod.py").read_text(encoding="utf-8") == "VALUE = 42\n"
    assert (tmp_path / "keep.py").read_text(encoding="utf-8") == "VALUE = 2\n"
    assert result.commands[0].exit_code == 0
    assert result.commands[0].stdout.strip() == "42"


def test_local_sandbox_reports_real_failures_and_deletes(tmp_path: Path):
    _write(tmp_path, "gone.py", "x = 1\n")
    sandbox = LocalSandbox(tmp_path)
    result = sandbox.run(
        [CommandSpec(argv=(PYTHON, "-c", "raise SystemExit(3)"))],
        _changeset(FileChange(path="gone.py", operation="delete")),
        "main",
    )
    assert not (tmp_path / "gone.py").exists()
    assert result.commands[0].exit_code == 3


def test_local_sandbox_validates_before_touching_the_tree(tmp_path: Path):
    _write(tmp_path, "a.py", "a = 1\n")
    sandbox = LocalSandbox(tmp_path)
    with pytest.raises(SandboxError):
        sandbox.run(
            [],
            _changeset(
                FileChange(path="b.py", operation="create", content="b = 1\n"),
                FileChange(path="a.py", operation="create", content="dup\n"),
            ),
            "main",
        )
    assert not (tmp_path / "b.py").exists()  # nothing was applied
    with pytest.raises(SandboxError):
        sandbox.run(
            [],
            _changeset(FileChange(path="../evil.py", operation="create", content="x")),
            "main",
        )


def test_local_sandbox_timeout_and_missing_executable(tmp_path: Path):
    sandbox = LocalSandbox(tmp_path)
    changes = _changeset(FileChange(path="a.py", operation="create", content="a = 1\n"))
    with pytest.raises(CommandTimeoutError):
        sandbox.run(
            [CommandSpec(
                argv=(PYTHON, "-c", "import time; time.sleep(30)"),
                timeout_seconds=1,
            )],
            changes,
            "main",
        )
    with pytest.raises(SandboxError):
        sandbox.run(
            [CommandSpec(argv=("definitely-not-a-real-executable-xyz",))],
            changes,
            "main",
        )


def test_workspace_routing_falls_back_without_a_root(tmp_path: Path):
    _write(tmp_path, "real.py", "REAL\n")
    workspace = LocalWorkspace({"local-proj": tmp_path})
    repository = WorkspaceRepository(workspace, InMemoryRepository())
    sandbox = WorkspaceSandbox(
        workspace,
        ScriptedSandbox(default_result=CommandResult(
            exit_code=0, stdout="fake", stderr="", duration_ms=1,
        )),
    )
    changes = _changeset(FileChange(path="new.py", operation="create", content="n\n"))

    # Unbound / unknown project: the fallbacks answer, the folder is untouched.
    workspace.bind("other-proj")
    with pytest.raises(FileNotFoundInRepository):
        repository.read_file("real.py", "main")
    assert sandbox.run([], changes, "main").commands == ()

    # Bound to the local project: real folder reads and writes.
    workspace.bind("local-proj")
    assert repository.read_file("real.py", "main") == "REAL\n"
    result = sandbox.run(
        [CommandSpec(argv=(PYTHON, "-c", "print(open('new.py').read().strip())"))],
        changes,
        "main",
    )
    assert result.commands[0].stdout.strip() == "n"
    assert (tmp_path / "new.py").exists()

    workspace.remove("local-proj")
    assert workspace.current_root() is None
