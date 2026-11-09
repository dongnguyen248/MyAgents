"""Applying a change set to a real folder, shared by the local sandboxes."""

from __future__ import annotations

import logging
from pathlib import Path, PurePosixPath, PureWindowsPath

from asf.tools.changeset import ChangeSet, FileChange
from asf.tools.ports import (
    AppliedRelabel,
    RepositoryError,
    SandboxApplyError,
    SandboxFailure,
)

logger = logging.getLogger(__name__)

__all__ = ["apply_changeset", "resolve_within"]


def resolve_within(root: Path, path: str) -> Path:
    """Resolve a repository-relative path, refusing anything outside root."""
    if (
        not path
        or PurePosixPath(path).is_absolute()
        or PureWindowsPath(path).is_absolute()
        or PureWindowsPath(path).drive
    ):
        raise RepositoryError(f"Path must be relative: {path!r}", path=path)
    resolved_root = root.resolve()
    candidate = (resolved_root / Path(*PurePosixPath(path).parts)).resolve()
    if not candidate.is_relative_to(resolved_root):
        raise RepositoryError(f"Path escapes the project folder: {path!r}", path=path)
    return candidate


def _apply_failure(root: Path) -> SandboxFailure:
    return SandboxFailure("start", "SandboxApplyError", cwd=root)


def _operation_for_missing(
    change: FileChange,
    relabels: list[AppliedRelabel],
    *,
    allow_relabel: bool,
    root: Path,
) -> str:
    if allow_relabel and change.operation == "modify" and change.content is not None:
        relabels.append(AppliedRelabel(change.path, "modify", "create"))
        logger.warning(
            "changeset relabel: %s labelled modify but absent from the "
            "working tree; applying as create (full content supplied)",
            change.path,
        )
        return "create"
    if change.operation == "modify":
        raise SandboxApplyError(
            f"apply failed: cannot modify missing file {change.path}",
            command=None,
            failure=_apply_failure(root),
        )
    raise SandboxApplyError(
        f"Cannot {change.operation} missing file: {change.path}",
        command=None,
        failure=_apply_failure(root),
    )


def _planned_targets(
    root: Path, changes: ChangeSet, *, allow_relabel: bool
) -> tuple[list[tuple[Path, str, str | None]], list[AppliedRelabel]]:
    targets: list[tuple[Path, str, str | None]] = []
    relabels: list[AppliedRelabel] = []
    for change in changes.changes:
        try:
            target = resolve_within(root, change.path)
        except RepositoryError as error:
            raise SandboxApplyError(
                str(error), command=None, failure=_apply_failure(root)
            ) from None
        exists = target.is_file()
        if change.operation == "create" and exists:
            raise SandboxApplyError(
                f"Cannot create existing file: {change.path}",
                command=None,
                failure=_apply_failure(root),
            )
        operation: str = change.operation
        if operation in ("modify", "delete") and not exists:
            operation = _operation_for_missing(
                change, relabels, allow_relabel=allow_relabel, root=root
            )
        targets.append((target, operation, change.content))
    return targets, relabels


def apply_changeset(
    root: Path, changes: ChangeSet, *, allow_relabel: bool
) -> tuple[AppliedRelabel, ...]:
    """Write a change set into root, validating the whole set first.

    A bad change set leaves the folder untouched. With
    ``allow_relabel`` — only for a managed worktree that was just reset
    to HEAD, which removes files an earlier change set created — a
    modify carrying the file's full content whose target is absent is
    applied as a create and reported in the returned relabels: the
    label was aligned with a tree state the reset destroyed, while the
    intent (set this path to this content) is unambiguous. Without it
    (a real project folder), a modify of a missing file is a hard
    failure naming the path, so a typo cannot silently create a file.
    A delete of a missing file always fails, naming the path.
    """
    if not root.is_dir():
        raise SandboxApplyError(
            f"apply failed: working directory does not exist: {root} "
            "(it may have been moved or removed; one possible cause is "
            "antivirus software)",
            command=None,
            failure=_apply_failure(root),
        )
    targets, relabels = _planned_targets(root, changes, allow_relabel=allow_relabel)
    for target, operation, content in targets:
        if operation == "delete":
            target.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((content or "").encode("utf-8"))
    return tuple(relabels)
