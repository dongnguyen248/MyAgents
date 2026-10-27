from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from asf.tools.changeset import ChangeSet, FileChange

__all__ = [
    "ImplementContext",
    "FixContext",
    "build_implement_context",
    "build_fix_context",
    "generate_changeset",
]


@dataclass(frozen=True)
class ImplementContext:
    """Context for the ImplementAgent LLM prompt."""

    task_id: str
    spec_summary: str
    plan_summary: str
    task_summary: str
    expected_files: tuple[str, ...]
    existing_files: dict[str, str]  # path -> content


@dataclass(frozen=True)
class FixContext:
    """Context for the FixAgent LLM prompt."""

    task_id: str
    spec_summary: str
    plan_summary: str
    task_summary: str
    expected_files: tuple[str, ...]
    existing_files: dict[str, str]
    review_findings: tuple[dict[str, Any], ...]  # serialized findings
    previous_changeset: ChangeSet | None


def build_implement_context(
    *,
    task_id: str,
    spec_summary: str,
    plan_summary: str,
    task_summary: str,
    expected_files: list[str],
    existing_files: dict[str, str],
) -> ImplementContext:
    """Build context for ImplementAgent."""
    return ImplementContext(
        task_id=task_id,
        spec_summary=spec_summary,
        plan_summary=plan_summary,
        task_summary=task_summary,
        expected_files=tuple(expected_files),
        existing_files=existing_files,
    )


def build_fix_context(
    *,
    task_id: str,
    spec_summary: str,
    plan_summary: str,
    task_summary: str,
    expected_files: list[str],
    existing_files: dict[str, str],
    review_findings: list[dict[str, Any]],
    previous_changeset: ChangeSet | None,
) -> FixContext:
    """Build context for FixAgent."""
    return FixContext(
        task_id=task_id,
        spec_summary=spec_summary,
        plan_summary=plan_summary,
        task_summary=task_summary,
        expected_files=tuple(expected_files),
        existing_files=existing_files,
        review_findings=tuple(review_findings),
        previous_changeset=previous_changeset,
    )


def generate_changeset(
    files: dict[str, str | None],
    *,
    base_files: dict[str, str] | None = None,
) -> ChangeSet:
    """Generate a ChangeSet from a dict of path -> content.

    Args:
        files: Dict mapping path to content. None means delete.
        base_files: Optional dict of existing files (path -> content) to determine operation.

    Returns:
        ChangeSet with appropriate operations (create/modify/delete).
    """
    base = base_files or {}
    changes: list[FileChange] = []

    for path, content in files.items():
        if content is None:
            # Delete
            changes.append(FileChange(path=path, operation="delete", content=None))
        elif path in base:
            # Modify (only if content differs)
            if base[path] != content:
                changes.append(FileChange(path=path, operation="modify", content=content))
        else:
            # Create
            changes.append(FileChange(path=path, operation="create", content=content))

    if not changes:
        # Return a ChangeSet with a dummy change that will be filtered out
        # Actually, we need to handle this differently - ChangeSet requires min_length=1
        # Let's return a ChangeSet with an empty list and handle validation elsewhere
        pass

    return ChangeSet(changes=changes)