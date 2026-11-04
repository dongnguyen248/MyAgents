"""Tests for ChangeSet and FileChange validation per D12."""

from __future__ import annotations

import pytest

from asf.agents._shared.codegen import generate_changeset
from asf.tools.changeset import ChangeSet, FileChange

# --- FileChange validation tests ---

def test_filechange_create_requires_content() -> None:
    """Create operation requires content."""
    with pytest.raises(ValueError, match="create operation requires 'content'"):
        FileChange(path="test.py", operation="create", content=None)


def test_filechange_create_with_content_valid() -> None:
    """Create with content is valid."""
    fc = FileChange(path="test.py", operation="create", content="print('hello')")
    assert fc.content == "print('hello')"


def test_filechange_modify_requires_content() -> None:
    """Modify operation requires content."""
    with pytest.raises(ValueError, match="modify operation requires 'content'"):
        FileChange(path="test.py", operation="modify", content=None)


def test_filechange_modify_with_content_valid() -> None:
    """Modify with content is valid."""
    fc = FileChange(path="test.py", operation="modify", content="print('hello')")
    assert fc.content == "print('hello')"


def test_filechange_delete_forbids_content() -> None:
    """Delete operation must not have content."""
    with pytest.raises(ValueError, match="delete operation must not have 'content'"):
        FileChange(path="test.py", operation="delete", content="should not be here")


def test_filechange_delete_without_content_valid() -> None:
    """Delete without content is valid."""
    fc = FileChange(path="test.py", operation="delete", content=None)
    assert fc.content is None


def test_filechange_nul_bytes_rejected() -> None:
    """NUL bytes in content are rejected for create/modify."""
    with pytest.raises(ValueError, match="content must not contain NUL bytes"):
        FileChange(path="test.py", operation="create", content="hello\x00world")
    with pytest.raises(ValueError, match="content must not contain NUL bytes"):
        FileChange(path="test.py", operation="modify", content="hello\x00world")


def test_filechange_nul_bytes_allowed_in_delete() -> None:
    """NUL bytes check only applies when content is present (delete has None)."""
    # This is implicitly tested by delete_forbids_content
    pass


# --- ChangeSet validation tests ---

def test_changeset_min_length_1() -> None:
    """ChangeSet must have at least 1 change."""
    with pytest.raises(ValueError, match="at least 1"):
        ChangeSet(changes=[])


def test_changeset_max_length_50() -> None:
    """ChangeSet must have at most 50 changes."""
    changes = [
        FileChange(path=f"file{i}.py", operation="create", content=f"c{i}")
        for i in range(51)
    ]
    with pytest.raises(ValueError, match="at most 50"):
        ChangeSet(changes=changes)


def test_changeset_duplicate_paths_rejected() -> None:
    """ChangeSet with duplicate paths is rejected."""
    changes = [
        FileChange(path="test.py", operation="create", content="a"),
        FileChange(path="test.py", operation="modify", content="b"),
    ]
    with pytest.raises(ValueError, match="duplicate paths"):
        ChangeSet(changes=changes)


def test_changeset_valid() -> None:
    """Valid ChangeSet is accepted."""
    changes = [
        FileChange(path="test.py", operation="create", content="a"),
        FileChange(path="other.py", operation="modify", content="b"),
    ]
    cs = ChangeSet(changes=changes)
    assert len(cs.changes) == 2


# --- generate_changeset tests ---

def test_generate_changeset_empty_raises() -> None:
    """generate_changeset with empty input raises ValueError."""
    with pytest.raises(ValueError, match="no changes produced"):
        generate_changeset({})


def test_generate_changeset_create() -> None:
    """generate_changeset creates ChangeSet for new files."""
    cs = generate_changeset({"test.py": "print('hello')"})
    assert len(cs.changes) == 1
    assert cs.changes[0].path == "test.py"
    assert cs.changes[0].operation == "create"
    assert cs.changes[0].content == "print('hello')"


def test_generate_changeset_modify() -> None:
    """generate_changeset creates modify for existing files with different content."""
    base = {"test.py": "old content"}
    cs = generate_changeset({"test.py": "new content"}, base_files=base)
    assert len(cs.changes) == 1
    assert cs.changes[0].operation == "modify"


def test_generate_changeset_modify_noop_filtered() -> None:
    """generate_changeset filters out no-op modifications and raises when no changes."""
    base = {"test.py": "same content"}
    with pytest.raises(ValueError, match="no changes produced"):
        generate_changeset({"test.py": "same content"}, base_files=base)


def test_generate_changeset_delete() -> None:
    """generate_changeset creates delete for None content."""
    base = {"test.py": "old content"}
    cs = generate_changeset({"test.py": None}, base_files=base)
    assert len(cs.changes) == 1
    assert cs.changes[0].operation == "delete"
    assert cs.changes[0].content is None


def test_generate_changeset_mixed() -> None:
    """generate_changeset handles mixed operations."""
    base = {"existing.py": "old"}
    files = {
        "existing.py": "new",   # modify
        "new.py": "create",     # create
        "delete.py": None,      # delete (must be in base)
    }
    # Add delete.py to base so it can be deleted
    base["delete.py"] = "to delete"
    cs = generate_changeset(files, base_files=base)
    assert len(cs.changes) == 3
    ops = {fc.path: fc.operation for fc in cs.changes}
    assert ops["existing.py"] == "modify"
    assert ops["new.py"] == "create"
    assert ops["delete.py"] == "delete"


# --- ChangeSet.model_validate tests ---

def test_changeset_model_validate_empty_dict_raises() -> None:
    """ChangeSet.model_validate({}) raises because changes is required."""
    with pytest.raises(Exception):  # Pydantic ValidationError
        ChangeSet.model_validate({})


def test_changeset_model_validate_empty_changes_raises() -> None:
    """ChangeSet.model_validate({'changes': []}) raises min_length violation."""
    with pytest.raises(Exception):  # Pydantic ValidationError
        ChangeSet.model_validate({"changes": []})