from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from asf.agents._shared.limits import (
    MAX_FILE_SIZE_BYTES,
    check_changeset_limits,
    check_file_size,
)
from asf.agents._shared.paths import check_denied_paths, find_out_of_scope
from asf.agents._shared.security import scan_secrets
from asf.tools.changeset import ChangeSet, FileChange
from asf.tools.ports import (
    FileNotFoundInRepository,
    FileTooLargeError,
    RepositoryError,
    RepositoryPort,
)

__all__ = [
    "ImplementContext",
    "FixContext",
    "build_implement_context",
    "build_fix_context",
    "generate_changeset",
    "normalize_changeset_operations",
    "validate_changeset",
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

    Raises:
        ValueError: If no changes would be generated (empty input or all modifications
                    result in no-ops). Per D12, ChangeSet requires min_length=1.
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
        raise ValueError(
            "generate_changeset: no changes produced (empty input or all modifications are no-ops)"
        )

    return ChangeSet(changes=changes)


def normalize_changeset_operations(
    changeset: ChangeSet, ref: str, repository: RepositoryPort,
) -> ChangeSet:
    """Align each change's operation with the repository's actual state.

    A change carries the file's FULL new content, so "create" and
    "modify" are two labels for one intent — set this path to this
    content. The label still gets picked wrong in practice: the fix
    contract asks for a replacement relative to the ORIGINAL base ref
    (where the file did not exist yet, so "create" reads correctly),
    while a local workspace folder already holds the implemented file.
    Rejecting the whole changeset for the label alone wastes the run,
    so rewrite the label to match reality. A delete of a file that
    does not exist is already satisfied and drops out. Genuine
    violations (scope, denied paths, content) are still caught by
    :func:`validate_changeset` afterwards.
    """
    changes: list[FileChange] = []
    for change in changeset.changes:
        try:
            repository.read_file(change.path, ref, max_bytes=MAX_FILE_SIZE_BYTES)
            exists = True
        except FileNotFoundInRepository:
            exists = False
        except FileTooLargeError:
            exists = True  # Present, just large; validation flags the size.
        except RepositoryError:
            changes.append(change)  # Cannot tell; leave it for validation.
            continue
        if change.operation == "delete":
            if exists:
                changes.append(change)
            continue
        operation = "modify" if exists else "create"
        changes.append(
            change if change.operation == operation
            else change.model_copy(update={"operation": operation})
        )
    # If every change dropped out (only deletes of missing files), keep
    # the original so validation can report the real problem instead of
    # an empty changeset.
    return ChangeSet(changes=changes) if changes else changeset


def validate_changeset(
    changeset: ChangeSet,
    expected_files: list[str],
    ref: str,
    repository: RepositoryPort,
) -> dict[str, Any] | None:
    """Validate generated files against the unchanged base, scope and content limits."""
    issues: dict[str, Any] = {}
    if not changeset.changes:
        return {"emptyChangeSet": "Change set must not be empty"}
    out_of_scope = find_out_of_scope(changeset, set(expected_files))
    if out_of_scope:
        issues["outOfScopePaths"] = out_of_scope
    for change in changeset.changes:
        for issue in check_denied_paths(change.path, None):
            if "always denied" in issue:
                issues.setdefault("deniedPaths", []).append({"path": change.path, "reason": issue})
        if change.content is not None:
            if "\x00" in change.content:
                issues.setdefault("contentIssues", []).append(
                    {"path": change.path, "issue": "content contains NUL bytes"}
                )
            try:
                size = len(change.content.encode("utf-8"))
            except UnicodeEncodeError:
                issues.setdefault("contentIssues", []).append(
                    {"path": change.path, "issue": "content is not valid UTF-8"}
                )
            else:
                for issue in check_file_size(size, change.path):
                    issues.setdefault("contentIssues", []).append(
                        {"path": change.path, "issue": issue}
                    )
            if not change.content.strip():
                issues.setdefault("contentIssues", []).append(
                    {"path": change.path, "issue": "content is whitespace-only"}
                )
        try:
            repository.read_file(change.path, ref, max_bytes=MAX_FILE_SIZE_BYTES)
        except FileNotFoundInRepository:
            if change.operation in ("modify", "delete"):
                issues.setdefault("missingPaths", []).append(
                    {"path": change.path, "operation": change.operation,
                     "reason": "file does not exist at ref"}
                )
        except FileTooLargeError:
            issues.setdefault("contentIssues", []).append(
                {"path": change.path, "issue": "file too large to verify existence"}
            )
        else:
            if change.operation == "create":
                issues.setdefault("existingPaths", []).append(
                    {"path": change.path, "operation": "create",
                     "reason": "file already exists at ref"}
                )
    limit_issues = check_changeset_limits(changeset)
    if limit_issues:
        issues["limitIssues"] = limit_issues
    return issues or None


def changeset_secret_issues(changeset: ChangeSet) -> list[dict[str, Any]]:
    return [
        {"path": change.path, "pattern": match.pattern_name, "line": match.line_number}
        for change in changeset.changes if change.content is not None
        for match in scan_secrets(change.content, change.path)
    ]