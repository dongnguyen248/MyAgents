from __future__ import annotations

import pytest

from asf.tools.changeset import ChangeSet, FileChange


def test_filechange_create_with_content() -> None:
    fc = FileChange(path="src/foo.py", operation="create", content="print('hello')")
    assert fc.path == "src/foo.py"
    assert fc.operation == "create"
    assert fc.content == "print('hello')"


def test_filechange_create_without_content_raises() -> None:
    with pytest.raises(ValueError, match="create operation requires 'content'"):
        FileChange(path="src/foo.py", operation="create", content=None)


def test_filechange_modify_with_content() -> None:
    fc = FileChange(path="src/foo.py", operation="modify", content="print('world')")
    assert fc.operation == "modify"
    assert fc.content == "print('world')"


def test_filechange_modify_without_content_raises() -> None:
    with pytest.raises(ValueError, match="modify operation requires 'content'"):
        FileChange(path="src/foo.py", operation="modify", content=None)


def test_filechange_delete_without_content() -> None:
    fc = FileChange(path="src/foo.py", operation="delete", content=None)
    assert fc.operation == "delete"
    assert fc.content is None


def test_filechange_delete_with_content_raises() -> None:
    with pytest.raises(ValueError, match="delete operation must not have 'content'"):
        FileChange(path="src/foo.py", operation="delete", content="something")


def test_filechange_invalid_operation_raises() -> None:
    with pytest.raises(ValueError, match="Input should be 'create', 'modify' or 'delete'"):
        FileChange(path="src/foo.py", operation="invalid", content="x")  # type: ignore


def test_filechange_path_validation() -> None:
    # FileChange model doesn't validate paths - that's done by validate_relative_path function
    # Just test that paths are stored as-is
    fc = FileChange(path="src/foo.py", operation="create", content="x")
    assert fc.path == "src/foo.py"
    fc = FileChange(path="/absolute/path.py", operation="create", content="x")
    assert fc.path == "/absolute/path.py"


def test_filechange_create_with_nul_bytes_raises() -> None:
    with pytest.raises(ValueError, match="content must not contain NUL bytes"):
        FileChange(path="src/foo.py", operation="create", content="print('\x00')")


def test_filechange_modify_with_nul_bytes_raises() -> None:
    with pytest.raises(ValueError, match="content must not contain NUL bytes"):
        FileChange(path="src/foo.py", operation="modify", content="print('\x00')")


def test_changeset_empty() -> None:
    cs = ChangeSet(changes=())
    assert len(cs.changes) == 0


def test_changeset_with_changes() -> None:
    changes = (
        FileChange(path="src/a.py", operation="create", content="a"),
        FileChange(path="src/b.py", operation="modify", content="b"),
        FileChange(path="src/c.py", operation="delete", content=None),
    )
    cs = ChangeSet(changes=changes)
    assert len(cs.changes) == 3


def test_changeset_no_duplicate_paths() -> None:
    changes = (
        FileChange(path="src/a.py", operation="create", content="a"),
        FileChange(path="src/a.py", operation="modify", content="b"),
    )
    with pytest.raises(ValueError, match="duplicate path"):
        ChangeSet(changes=changes)


def test_changeset_frozen() -> None:
    cs = ChangeSet(changes=())
    with pytest.raises(Exception):
        cs.changes = ()  # type: ignore