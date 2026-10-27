from __future__ import annotations

from asf.agents._shared.limits import (
    MAX_CHANGES_PER_CHANGESET,
    MAX_COMMAND_OUTPUT_BYTES,
    MAX_FILE_SIZE_BYTES,
    MAX_TOTAL_CONTENT_BYTES,
    check_changeset_limits,
    check_command_output_size,
    check_file_size,
)
from asf.tools.changeset import ChangeSet, FileChange


def test_check_file_size_within_limit() -> None:
    assert check_file_size(1000, "test.py") == []


def test_check_file_size_at_limit() -> None:
    assert check_file_size(MAX_FILE_SIZE_BYTES, "test.py") == []


def test_check_file_size_over_limit() -> None:
    issues = check_file_size(MAX_FILE_SIZE_BYTES + 1, "test.py")
    assert len(issues) == 1
    assert "exceeds limit" in issues[0]
    assert "test.py" in issues[0]


def test_check_command_output_size_within_limit() -> None:
    assert check_command_output_size(1000, "ls") == []


def test_check_command_output_size_at_limit() -> None:
    assert check_command_output_size(MAX_COMMAND_OUTPUT_BYTES, "ls") == []


def test_check_command_output_size_over_limit() -> None:
    issues = check_command_output_size(MAX_COMMAND_OUTPUT_BYTES + 1, "ls")
    assert len(issues) == 1
    assert "exceeds limit" in issues[0]
    assert "ls" in issues[0]


def test_check_changeset_limits_within_limits() -> None:
    changeset = ChangeSet(changes=(
        FileChange(path="a.py", operation="create", content="a"),
        FileChange(path="b.py", operation="create", content="b"),
    ))
    assert check_changeset_limits(changeset) == []


def test_check_changeset_limits_too_many_changes() -> None:
    changes = tuple(
        FileChange(path=f"f{i}.py", operation="create", content="x")
        for i in range(MAX_CHANGES_PER_CHANGESET + 1)
    )
    changeset = ChangeSet(changes=changes)
    issues = check_changeset_limits(changeset)
    assert len(issues) == 1
    assert "exceeds limit" in issues[0]


def test_check_changeset_limits_total_content_over_limit() -> None:
    large_content = "x" * (MAX_TOTAL_CONTENT_BYTES // 2 + 1)
    changeset = ChangeSet(changes=(
        FileChange(path="a.py", operation="create", content=large_content),
        FileChange(path="b.py", operation="create", content=large_content),
    ))
    issues = check_changeset_limits(changeset)
    assert len(issues) == 1
    assert "total content size" in issues[0]


def test_check_changeset_limits_empty_changeset() -> None:
    changeset = ChangeSet(changes=())
    assert check_changeset_limits(changeset) == []