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
    "changeset_secret_issues",
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
    # Why the previous fix attempt was rejected, when this execution
    # re-attempts a fix (step retry or a resumed run): the model must
    # correct that specific failure instead of repeating it.
    previous_error: str | None = None
    # Bounded repository map (tree + neighbour outlines); "" when
    # the assembly disabled it.
    repo_map: str = ""


def generate_changeset(
    files: dict[str, str | None],
    *,
    base_files: dict[str, str] | None = None,
) -> ChangeSet:
    """Generate a ChangeSet from a dict of path -> content.

    A None content means delete. Raises ValueError when no changes
    would be generated (empty input or all modifications are no-ops):
    per D12, ChangeSet requires min_length=1.
    """
    base = base_files or {}
    changes: list[FileChange] = []
    for path, content in files.items():
        change = _change_for(path, content, base)
        if change is not None:
            changes.append(change)
    if not changes:
        raise ValueError(
            "generate_changeset: no changes produced (empty input or all modifications are no-ops)"
        )
    return ChangeSet(changes=changes)


def _change_for(path: str, content: str | None, base: dict[str, str]) -> FileChange | None:
    if content is None:
        return FileChange(path=path, operation="delete", content=None)
    if path in base:
        if base[path] != content:
            return FileChange(path=path, operation="modify", content=content)
        return None
    return FileChange(path=path, operation="create", content=content)


def normalize_changeset_operations(
    changeset: ChangeSet,
    ref: str,
    repository: RepositoryPort,
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
            change
            if change.operation == operation
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
    if not changeset.changes:
        return {"emptyChangeSet": "Change set must not be empty"}
    issues: dict[str, Any] = {}
    out_of_scope = find_out_of_scope(changeset, set(expected_files))
    if out_of_scope:
        issues["outOfScopePaths"] = out_of_scope
    for change in changeset.changes:
        _validate_change(change, ref, repository, issues)
    limit_issues = check_changeset_limits(changeset)
    if limit_issues:
        issues["limitIssues"] = limit_issues
    return issues or None


def _validate_change(
    change: FileChange,
    ref: str,
    repository: RepositoryPort,
    issues: dict[str, Any],
) -> None:
    _denied_path_issues(change, issues)
    if change.content is not None:
        _content_issues(change, issues)
    _existence_issues(change, ref, repository, issues)


def _denied_path_issues(change: FileChange, issues: dict[str, Any]) -> None:
    for issue in check_denied_paths(change.path, None):
        if "always denied" in issue:
            issues.setdefault("deniedPaths", []).append({"path": change.path, "reason": issue})


def _content_issues(change: FileChange, issues: dict[str, Any]) -> None:
    content = change.content or ""
    if "\x00" in content:
        _add_content_issue(issues, change.path, "content contains NUL bytes")
    _size_issues(change, issues)
    if not content.strip():
        _add_content_issue(issues, change.path, "content is whitespace-only")


def _size_issues(change: FileChange, issues: dict[str, Any]) -> None:
    try:
        size = len((change.content or "").encode("utf-8"))
    except UnicodeEncodeError:
        _add_content_issue(issues, change.path, "content is not valid UTF-8")
        return
    for issue in check_file_size(size, change.path):
        _add_content_issue(issues, change.path, issue)


def _add_content_issue(issues: dict[str, Any], path: str, issue: str) -> None:
    issues.setdefault("contentIssues", []).append({"path": path, "issue": issue})


def _existence_issues(
    change: FileChange,
    ref: str,
    repository: RepositoryPort,
    issues: dict[str, Any],
) -> None:
    try:
        repository.read_file(change.path, ref, max_bytes=MAX_FILE_SIZE_BYTES)
    except FileNotFoundInRepository:
        if change.operation in ("modify", "delete"):
            issues.setdefault("missingPaths", []).append(
                {
                    "path": change.path,
                    "operation": change.operation,
                    "reason": "file does not exist at ref",
                }
            )
    except FileTooLargeError:
        _add_content_issue(issues, change.path, "file too large to verify existence")
    else:
        if change.operation == "create":
            issues.setdefault("existingPaths", []).append(
                {
                    "path": change.path,
                    "operation": "create",
                    "reason": "file already exists at ref",
                }
            )


def changeset_secret_issues(changeset: ChangeSet) -> list[dict[str, Any]]:
    return [
        {"path": change.path, "pattern": match.pattern_name, "line": match.line_number}
        for change in changeset.changes
        if change.content is not None
        for match in scan_secrets(change.content, change.path)
    ]
