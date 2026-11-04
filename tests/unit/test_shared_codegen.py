from __future__ import annotations

import pytest

from asf.agents._shared.codegen import (
    build_fix_context,
    build_implement_context,
    generate_changeset,
    normalize_changeset_operations,
)
from asf.tools.changeset import ChangeSet, FileChange
from asf.tools.fake import InMemoryRepository


def test_build_implement_context() -> None:
    ctx = build_implement_context(
        task_id="task-123",
        spec_summary="Spec summary",
        plan_summary="Plan summary",
        task_summary="Task summary",
        expected_files=["src/a.py", "src/b.py"],
        existing_files={"src/a.py": "old content"},
    )
    assert ctx.task_id == "task-123"
    assert ctx.spec_summary == "Spec summary"
    assert ctx.plan_summary == "Plan summary"
    assert ctx.task_summary == "Task summary"
    assert ctx.expected_files == ("src/a.py", "src/b.py")
    assert ctx.existing_files == {"src/a.py": "old content"}


def test_build_fix_context() -> None:
    changeset = ChangeSet(changes=(
        FileChange(path="src/a.py", operation="modify", content="new"),
    ))
    ctx = build_fix_context(
        task_id="task-123",
        spec_summary="Spec summary",
        plan_summary="Plan summary",
        task_summary="Task summary",
        expected_files=["src/a.py", "src/b.py"],
        existing_files={"src/a.py": "old content"},
        review_findings=[
            {
                "id": "f1",
                "severity": "MAJOR",
                "file": "a.py",
                "line": 1,
                "message": "Issue",
            },
        ],
        previous_changeset=changeset,
    )
    assert ctx.task_id == "task-123"
    assert ctx.review_findings == (
        {
            "id": "f1",
            "severity": "MAJOR",
            "file": "a.py",
            "line": 1,
            "message": "Issue",
        },
    )
    assert ctx.previous_changeset == changeset


def test_build_fix_context_no_previous() -> None:
    ctx = build_fix_context(
        task_id="task-123",
        spec_summary="Spec",
        plan_summary="Plan",
        task_summary="Task",
        expected_files=["src/a.py"],
        existing_files={},
        review_findings=[],
        previous_changeset=None,
    )
    assert ctx.previous_changeset is None


def test_generate_changeset_create_new_files() -> None:
    files = {"src/new1.py": "content1", "src/new2.py": "content2"}
    cs = generate_changeset(files)
    assert len(cs.changes) == 2
    for fc in cs.changes:
        assert fc.operation == "create"
        assert fc.content is not None


def test_generate_changeset_modify_existing_files() -> None:
    base = {"src/existing.py": "old content"}
    files = {"src/existing.py": "new content"}
    cs = generate_changeset(files, base_files=base)
    assert len(cs.changes) == 1
    assert cs.changes[0].operation == "modify"
    assert cs.changes[0].content == "new content"


def test_generate_changeset_delete_files() -> None:
    base = {"src/todelete.py": "content"}
    files = {"src/todelete.py": None}
    cs = generate_changeset(files, base_files=base)
    assert len(cs.changes) == 1
    assert cs.changes[0].operation == "delete"
    assert cs.changes[0].content is None


def test_generate_changeset_no_change_for_identical_content() -> None:
    """generate_changeset raises when no changes (min_length=1 per D12)."""
    base = {"src/same.py": "content"}
    files = {"src/same.py": "content"}
    with pytest.raises(ValueError, match="no changes produced"):
        generate_changeset(files, base_files=base)


def test_generate_changeset_mixed_operations() -> None:
    base = {"src/keep.py": "keep", "src/modify.py": "old", "src/delete.py": "del"}
    files = {
        "src/keep.py": "keep",  # no change
        "src/modify.py": "new",  # modify
        "src/delete.py": None,  # delete
        "src/create.py": "new",  # create
    }
    cs = generate_changeset(files, base_files=base)
    assert len(cs.changes) == 3
    ops = {fc.path: fc.operation for fc in cs.changes}
    assert ops["src/modify.py"] == "modify"
    assert ops["src/delete.py"] == "delete"
    assert ops["src/create.py"] == "create"

def _repo(files: dict[str, str]) -> InMemoryRepository:
    return InMemoryRepository({"main": files})


def test_normalize_create_for_existing_file_becomes_modify() -> None:
    changeset = ChangeSet(changes=(
        FileChange(path="src/a.py", operation="create", content="new"),
    ))
    result = normalize_changeset_operations(
        changeset, "main", _repo({"src/a.py": "old"}),
    )
    assert result.changes[0].operation == "modify"
    assert result.changes[0].content == "new"


def test_normalize_modify_for_missing_file_becomes_create() -> None:
    changeset = ChangeSet(changes=(
        FileChange(path="src/a.py", operation="modify", content="new"),
    ))
    result = normalize_changeset_operations(changeset, "main", _repo({}))
    assert result.changes[0].operation == "create"


def test_normalize_keeps_correct_labels_and_drops_satisfied_deletes() -> None:
    changeset = ChangeSet(changes=(
        FileChange(path="src/a.py", operation="modify", content="new"),
        FileChange(path="src/b.py", operation="create", content="new"),
        FileChange(path="src/c.py", operation="delete"),  # missing: satisfied
        FileChange(path="src/d.py", operation="delete"),  # exists: kept
    ))
    result = normalize_changeset_operations(
        changeset, "main", _repo({"src/a.py": "old", "src/d.py": "old"}),
    )
    assert [(c.path, c.operation) for c in result.changes] == [
        ("src/a.py", "modify"), ("src/b.py", "create"), ("src/d.py", "delete"),
    ]


def test_normalize_all_dropped_returns_original_for_validation() -> None:
    changeset = ChangeSet(changes=(
        FileChange(path="src/c.py", operation="delete"),
    ))
    result = normalize_changeset_operations(changeset, "main", _repo({}))
    assert result is changeset
