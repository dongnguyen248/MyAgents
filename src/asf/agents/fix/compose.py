"""Composing a fix reply onto the effective state: the checks that
keep the composed replacement complete and its deletes honest."""

from __future__ import annotations

from collections.abc import Collection

from asf.agents._shared.repair import RepairableOutputError
from asf.tools.changeset import ChangeSet

__all__ = [
    "check_completeness",
    "check_delete_targets",
    "compose_replacement",
    "effective_existing",
]


def effective_existing(existing: dict[str, str], previous_changeset: ChangeSet) -> dict[str, str]:
    # Edit blocks are written against the state the model is
    # revising: the base files with the previous changeset applied.
    # Untouched previous changes carry over into the replacement.
    effective = dict(existing)
    for change in previous_changeset.changes:
        if change.operation == "delete":
            effective.pop(change.path, None)
        elif change.content is not None:
            effective[change.path] = change.content
    return effective


def compose_replacement(
    previous_changeset: ChangeSet, existing: dict[str, str], edits: ChangeSet
) -> ChangeSet:
    """The replacement is the previous changeset with the edits
    applied: an edit wins over the previous change for its path, a
    delete of a base file stays a delete, and a delete of a file the
    previous changeset created removes that change outright (relative
    to the base the file never exists)."""
    merged = {change.path: change for change in previous_changeset.changes}
    for change in edits.changes:
        if change.operation == "delete" and change.path not in existing:
            merged.pop(change.path, None)
        else:
            merged[change.path] = change
    if not merged:
        raise RepairableOutputError(
            "Replacement is empty after composing the edits",
            model_message=(
                "Your edits remove every file, leaving an empty "
                "replacement, which is not a valid fix. Keep at least "
                "one change: the remaining files must still implement "
                "the task."
            ),
            details={"reason": "empty-replacement"},
        )
    return ChangeSet(changes=list(merged.values()))


def check_delete_targets(effective_paths: Collection[str], edits: ChangeSet) -> None:
    """A delete edit must name a file of the effective state.

    The effective state is the base files with the previous changeset
    applied — the state the model's edits were written against.
    Deleting anything else is not a silent no-op: the failure is
    repairable, so the model is told the path does not exist there
    and can correct the reply.
    """
    for change in edits.changes:
        if change.operation == "delete" and change.path not in effective_paths:
            raise RepairableOutputError(
                f"Delete target does not exist: {change.path}",
                model_message=(
                    f"Your reply deletes {change.path}, which does not exist "
                    "in the effective state (the base files with the previous "
                    "changeset applied). Remove that delete, or delete a "
                    "file that exists there. Omitting a file never deletes it."
                ),
                details={"path": change.path, "reason": "delete-target-missing"},
            )


def check_completeness(previous: ChangeSet, edits: ChangeSet, replacement: ChangeSet) -> None:
    """Every previous path must survive composition or be deleted.

    Composition carries untouched previous changes over, so a path
    can only go missing here if composition is bypassed or broken;
    the guard turns that silent loss into a repairable error instead
    of a quietly smaller replacement.
    """
    kept = {change.path for change in replacement.changes}
    deleted = {change.path for change in edits.changes if change.operation == "delete"}
    missing = sorted(
        change.path
        for change in previous.changes
        if change.path not in kept and change.path not in deleted
    )
    if missing:
        raise RepairableOutputError(
            "Replacement drops previous files without an explicit delete",
            model_message=(
                "The replacement loses these files from the previous "
                "changeset without deleting them explicitly: "
                + ", ".join(missing)
                + ". Restore them, or delete each one explicitly if it "
                "must go."
            ),
            details={"missingPaths": missing},
        )
