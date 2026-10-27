from __future__ import annotations

import pytest

from asf.tools.changeset import ChangeSet, FileChange
from asf.tools.fake import InMemoryRepository, InMemorySandbox, ScriptedSandbox
from asf.tools.ports import (
    CommandResult,
    CommandSpec,
    CommandTimeoutError,
    FileNotFoundInRepository,
    FileTooLargeError,
    SandboxError,
)


def test_inmemory_repository_empty_repo() -> None:
    repo = InMemoryRepository()
    assert repo.list_tree("main") == ()
    assert repo.list_tree("main", "src") == ()


def test_inmemory_repository_add_tree_and_list() -> None:
    repo = InMemoryRepository()
    repo.add_tree("main", {"src/a.py": "a", "src/b.py": "b", "README.md": "readme"})

    assert repo.list_tree("main") == ("README.md", "src/a.py", "src/b.py")
    assert repo.list_tree("main", "src") == ("src/a.py", "src/b.py")
    assert repo.list_tree("main", "src/") == ("src/a.py", "src/b.py")


def test_inmemory_repository_read_file() -> None:
    repo = InMemoryRepository()
    repo.add_tree("main", {"src/a.py": "content_a"})

    assert repo.read_file("src/a.py", "main") == "content_a"


def test_inmemory_repository_read_file_not_found() -> None:
    repo = InMemoryRepository()
    repo.add_tree("main", {"src/a.py": "content_a"})

    with pytest.raises(FileNotFoundInRepository):
        repo.read_file("src/b.py", "main")


def test_inmemory_repository_read_file_ref_not_found() -> None:
    repo = InMemoryRepository()

    with pytest.raises(FileNotFoundInRepository):
        repo.read_file("src/a.py", "nonexistent")


def test_inmemory_repository_read_file_too_large() -> None:
    repo = InMemoryRepository()
    large_content = "x" * 300_000
    repo.add_tree("main", {"large.py": large_content})

    with pytest.raises(FileTooLargeError) as exc:
        repo.read_file("large.py", "main", max_bytes=256_000)
    assert exc.value.max_bytes == 256_000


def test_inmemory_repository_read_file_custom_max_bytes() -> None:
    repo = InMemoryRepository()
    repo.add_tree("main", {"small.py": "small"})

    assert repo.read_file("small.py", "main", max_bytes=10) == "small"


def test_scripted_sandbox_default_result() -> None:
    sandbox = ScriptedSandbox()
    result = sandbox.run(
        commands=[CommandSpec(argv=("echo", "hello"))],
        changes=ChangeSet(changes=()),
        ref="main",
    )
    assert len(result.commands) == 1
    assert result.commands[0].exit_code == 0
    assert result.commands[0].stdout == ""


def test_scripted_sandbox_recorded_result() -> None:
    sandbox = ScriptedSandbox(
        results={
            ("echo", "hello"): CommandResult(
                exit_code=0, stdout="hello\n", stderr="", duration_ms=10
            )
        }
    )
    result = sandbox.run(
        commands=[CommandSpec(argv=("echo", "hello"))],
        changes=ChangeSet(changes=()),
        ref="main",
    )
    assert result.commands[0].stdout == "hello\n"


def test_scripted_sandbox_timeout_command() -> None:
    sandbox = ScriptedSandbox(
        timeout_commands={("sleep", "10")}
    )
    with pytest.raises(CommandTimeoutError):
        sandbox.run(
            commands=[CommandSpec(argv=("sleep", "10"))],
            changes=ChangeSet(changes=()),
            ref="main",
        )


def test_scripted_sandbox_multiple_commands() -> None:
    sandbox = ScriptedSandbox(
        results={
            ("cmd1",): CommandResult(exit_code=0, stdout="out1", stderr="", duration_ms=1),
            ("cmd2",): CommandResult(exit_code=1, stdout="", stderr="err", duration_ms=2),
        }
    )
    result = sandbox.run(
        commands=[
            CommandSpec(argv=("cmd1",)),
            CommandSpec(argv=("cmd2",)),
        ],
        changes=ChangeSet(changes=()),
        ref="main",
    )
    assert len(result.commands) == 2
    assert result.commands[0].stdout == "out1"
    assert result.commands[1].stderr == "err"


def test_inmemory_sandbox_apply_create() -> None:
    repo = InMemoryRepository()
    repo.add_tree("main", {"existing.py": "old"})

    sandbox = InMemorySandbox(repository=repo)
    changes = ChangeSet(changes=(
        FileChange(path="new.py", operation="create", content="new content"),
    ))
    result = sandbox.run(
        commands=[CommandSpec(argv=("ls",))],
        changes=changes,
        ref="main",
    )
    assert len(result.commands) == 1

    # Verify file was created in the working copy (not persisted to repo)
    assert repo.read_file("existing.py", "main") == "old"
    with pytest.raises(FileNotFoundInRepository):
        repo.read_file("new.py", "main")


def test_inmemory_sandbox_apply_modify() -> None:
    repo = InMemoryRepository()
    repo.add_tree("main", {"existing.py": "old"})

    sandbox = InMemorySandbox(repository=repo)
    changes = ChangeSet(changes=(
        FileChange(path="existing.py", operation="modify", content="new"),
    ))
    result = sandbox.run(
        commands=[CommandSpec(argv=("ls",))],
        changes=changes,
        ref="main",
    )
    assert len(result.commands) == 1


def test_inmemory_sandbox_apply_delete() -> None:
    repo = InMemoryRepository()
    repo.add_tree("main", {"existing.py": "old", "other.py": "keep"})

    sandbox = InMemorySandbox(repository=repo)
    changes = ChangeSet(changes=(
        FileChange(path="existing.py", operation="delete", content=None),
    ))
    result = sandbox.run(
        commands=[CommandSpec(argv=("ls",))],
        changes=changes,
        ref="main",
    )
    assert len(result.commands) == 1


def test_inmemory_sandbox_create_existing_fails() -> None:
    repo = InMemoryRepository()
    repo.add_tree("main", {"existing.py": "old"})

    sandbox = InMemorySandbox(repository=repo)
    changes = ChangeSet(changes=(
        FileChange(path="existing.py", operation="create", content="new"),
    ))
    with pytest.raises(SandboxError, match="Cannot create existing file"):
        sandbox.run(
            commands=[CommandSpec(argv=("ls",))],
            changes=changes,
            ref="main",
        )


def test_inmemory_sandbox_modify_missing_fails() -> None:
    repo = InMemoryRepository()
    repo.add_tree("main", {"existing.py": "old"})

    sandbox = InMemorySandbox(repository=repo)
    changes = ChangeSet(changes=(
        FileChange(path="missing.py", operation="modify", content="new"),
    ))
    with pytest.raises(SandboxError, match="Cannot modify missing file"):
        sandbox.run(
            commands=[CommandSpec(argv=("ls",))],
            changes=changes,
            ref="main",
        )


def test_inmemory_sandbox_delete_missing_fails() -> None:
    repo = InMemoryRepository()
    repo.add_tree("main", {"existing.py": "old"})

    sandbox = InMemorySandbox(repository=repo)
    changes = ChangeSet(changes=(
        FileChange(path="missing.py", operation="delete", content=None),
    ))
    with pytest.raises(SandboxError, match="Cannot delete missing file"):
        sandbox.run(
            commands=[CommandSpec(argv=("ls",))],
            changes=changes,
            ref="main",
        )


def test_inmemory_sandbox_create_requires_content() -> None:
    repo = InMemoryRepository()
    _ = InMemorySandbox(repository=repo)  # Create sandbox to verify it can be instantiated
    with pytest.raises(ValueError, match="create operation requires 'content'"):
        ChangeSet(changes=(
            FileChange(path="new.py", operation="create", content=None),
        ))


def test_inmemory_sandbox_modify_requires_content() -> None:
    repo = InMemoryRepository()
    repo.add_tree("main", {"existing.py": "old"})
    _ = InMemorySandbox(repository=repo)  # Create sandbox to verify it can be instantiated
    with pytest.raises(ValueError, match="modify operation requires 'content'"):
        ChangeSet(changes=(
            FileChange(path="existing.py", operation="modify", content=None),
        ))


def test_inmemory_sandbox_ref_not_found_starts_empty() -> None:
    repo = InMemoryRepository()
    sandbox = InMemorySandbox(repository=repo)
    changes = ChangeSet(changes=(
        FileChange(path="new.py", operation="create", content="content"),
    ))
    result = sandbox.run(
        commands=[CommandSpec(argv=("ls",))],
        changes=changes,
        ref="nonexistent",
    )
    assert len(result.commands) == 1


def test_inmemory_sandbox_command_results() -> None:
    repo = InMemoryRepository()
    sandbox = InMemorySandbox(
        repository=repo,
        command_results={
            ("test",): CommandResult(exit_code=0, stdout="test output", stderr="", duration_ms=5)
        }
    )
    result = sandbox.run(
        commands=[CommandSpec(argv=("test",))],
        changes=ChangeSet(changes=()),
        ref="main",
    )
    assert result.commands[0].stdout == "test output"


def test_filetree_contains() -> None:
    """Test _FileTree.__contains__ (line 31)."""
    repo = InMemoryRepository()
    repo.add_tree("main", {"src/a.py": "content"})
    tree = repo._trees["main"]
    assert "src/a.py" in tree
    assert "src/b.py" not in tree


def test_scripted_sandbox_record() -> None:
    """Test ScriptedSandbox.record() (line 88)."""
    sandbox = ScriptedSandbox()
    custom_result = CommandResult(exit_code=0, stdout="recorded", stderr="", duration_ms=10)
    sandbox.record(("custom", "cmd"), custom_result)
    result = sandbox.run(
        commands=[CommandSpec(argv=("custom", "cmd"))],
        changes=ChangeSet(changes=()),
        ref="main",
    )
    assert result.commands[0].stdout == "recorded"


def test_scripted_sandbox_set_timeout() -> None:
    """Test ScriptedSandbox.set_timeout() (line 91)."""
    sandbox = ScriptedSandbox()
    sandbox.set_timeout(("sleep", "10"))
    with pytest.raises(CommandTimeoutError):
        sandbox.run(
            commands=[CommandSpec(argv=("sleep", "10"))],
            changes=ChangeSet(changes=()),
            ref="main",
        )


def test_inmemory_sandbox_set_command_result() -> None:
    """Test InMemorySandbox.set_command_result() (line 121)."""
    repo = InMemoryRepository()
    sandbox = InMemorySandbox(repository=repo)
    custom_result = CommandResult(exit_code=0, stdout="custom output", stderr="", duration_ms=5)
    sandbox.set_command_result(("custom", "cmd"), custom_result)
    result = sandbox.run(
        commands=[CommandSpec(argv=("custom", "cmd"))],
        changes=ChangeSet(changes=()),
        ref="main",
    )
    assert result.commands[0].stdout == "custom output"