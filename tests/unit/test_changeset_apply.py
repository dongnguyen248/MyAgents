"""Change-set application against a real folder (asf.tools.changeset_apply)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from pydantic import ValidationError

from asf.tools.changeset import ChangeSet, FileChange
from asf.tools.changeset_apply import apply_changeset
from asf.tools.fake import InMemoryRepository, InMemorySandbox
from asf.tools.local import LocalSandbox
from asf.tools.ports import AppliedRelabel, SandboxError


def _changeset(*changes: FileChange) -> ChangeSet:
    return ChangeSet(changes=list(changes))


def test_modify_with_content_for_missing_file_applies_as_create(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    changes = _changeset(FileChange(path="docs/decisions.md", operation="modify", content="v2\n"))
    with caplog.at_level(logging.WARNING, logger="asf.tools.changeset_apply"):
        relabels = apply_changeset(tmp_path, changes, allow_relabel=True)
    assert relabels == (AppliedRelabel("docs/decisions.md", "modify", "create"),)
    assert (tmp_path / "docs" / "decisions.md").read_text(encoding="utf-8") == "v2\n"
    assert "docs/decisions.md" in caplog.text
    assert "applying as create" in caplog.text


def test_modify_without_content_is_rejected_before_the_sandbox() -> None:
    # The changeset model itself forbids a content-less modify, so the
    # case fails explicitly at construction and can never reach apply;
    # the sandbox's own missing-content branch is defence in depth.
    with pytest.raises(ValidationError, match="modify operation requires 'content'"):
        FileChange(path="docs/decisions.md", operation="modify", content=None)


def test_delete_of_missing_file_fails_naming_the_path(tmp_path: Path) -> None:
    changes = _changeset(FileChange(path="docs/decisions.md", operation="delete", content=None))
    with pytest.raises(SandboxError, match="Cannot delete missing file: docs/decisions.md"):
        apply_changeset(tmp_path, changes, allow_relabel=True)


def test_create_of_existing_file_still_fails(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("base\n", encoding="utf-8")
    changes = _changeset(FileChange(path="app.py", operation="create", content="new\n"))
    with pytest.raises(SandboxError, match="Cannot create existing file: app.py"):
        apply_changeset(tmp_path, changes, allow_relabel=True)


def test_modify_of_existing_file_applies_without_relabel(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("base\n", encoding="utf-8")
    changes = _changeset(FileChange(path="app.py", operation="modify", content="next\n"))
    relabels = apply_changeset(tmp_path, changes, allow_relabel=True)
    assert relabels == ()
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "next\n"


def test_invalid_set_leaves_the_folder_untouched(tmp_path: Path) -> None:
    changes = _changeset(
        FileChange(path="new.py", operation="create", content="x\n"),
        FileChange(path="ghost.py", operation="delete", content=None),
    )
    with pytest.raises(SandboxError, match="Cannot delete missing file: ghost.py"):
        apply_changeset(tmp_path, changes, allow_relabel=True)
    assert not (tmp_path / "new.py").exists()


def test_escaping_path_is_rejected(tmp_path: Path) -> None:
    changes = _changeset(FileChange(path="../evil.py", operation="create", content="x\n"))
    with pytest.raises(SandboxError, match="escapes the project folder"):
        apply_changeset(tmp_path, changes, allow_relabel=True)


def test_modify_with_content_for_missing_file_fails_without_relabel(tmp_path: Path) -> None:
    # Direct mode (a real project folder, no reset): a modify of a
    # missing file is a hard failure naming the path, so a typo in the
    # changeset cannot silently create a file in the user's folder.
    changes = _changeset(FileChange(path="docs/decisions.md", operation="modify", content="v2\n"))
    with pytest.raises(SandboxError, match="Cannot modify missing file: docs/decisions.md"):
        apply_changeset(tmp_path, changes, allow_relabel=False)
    assert not (tmp_path / "docs" / "decisions.md").exists()


def test_local_sandbox_is_strict_by_default(tmp_path: Path) -> None:
    changes = _changeset(FileChange(path="docs/decisions.md", operation="modify", content="v2\n"))
    with pytest.raises(SandboxError, match="Cannot modify missing file: docs/decisions.md"):
        LocalSandbox(tmp_path).run([], changes, "main")
    assert not (tmp_path / "docs" / "decisions.md").exists()


def test_local_sandbox_result_carries_relabels(tmp_path: Path) -> None:
    changes = _changeset(FileChange(path="docs/decisions.md", operation="modify", content="v2\n"))
    result = LocalSandbox(tmp_path, allow_relabel=True).run([], changes, "main")
    assert result.relabels == (AppliedRelabel("docs/decisions.md", "modify", "create"),)
    assert (tmp_path / "docs" / "decisions.md").read_text(encoding="utf-8") == "v2\n"


def test_in_memory_sandbox_mirrors_the_relabel() -> None:
    sandbox = InMemorySandbox(InMemoryRepository())
    changes = _changeset(FileChange(path="docs/decisions.md", operation="modify", content="v2\n"))
    result = sandbox.run([], changes, "main")
    assert result.relabels == (AppliedRelabel("docs/decisions.md", "modify", "create"),)


def test_in_memory_sandbox_delete_of_missing_file_still_fails() -> None:
    sandbox = InMemorySandbox(InMemoryRepository())
    changes = _changeset(FileChange(path="docs/decisions.md", operation="delete", content=None))
    with pytest.raises(SandboxError, match="Cannot delete missing file: docs/decisions.md"):
        sandbox.run([], changes, "main")
