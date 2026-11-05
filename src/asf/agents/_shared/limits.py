from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from asf.tools.changeset import ChangeSet

__all__ = [
    "MAX_FILE_SIZE_BYTES",
    "MAX_COMMAND_OUTPUT_BYTES",
    "MAX_COMMAND_TIMEOUT_SECONDS",
    "MAX_CHANGES_PER_CHANGESET",
    "MAX_TOTAL_CONTENT_BYTES",
    "check_file_size",
    "check_command_output_size",
    "check_changeset_limits",
]


# Constants
MAX_FILE_SIZE_BYTES = 256_000
MAX_COMMAND_OUTPUT_BYTES = 64_000
MAX_COMMAND_TIMEOUT_SECONDS = 120
MAX_CHANGES_PER_CHANGESET = 50
MAX_TOTAL_CONTENT_BYTES = 1_000_000  # 1MB total for all file contents in a ChangeSet


def check_file_size(size: int, path: str) -> list[str]:
    """Check if a file size exceeds the limit.

    Args:
        size: File size in bytes.
        path: File path (for error messages).

    Returns:
        List of issue strings (empty if within limit).
    """
    issues: list[str] = []
    if size > MAX_FILE_SIZE_BYTES:
        issues.append(
            f"file '{path}' size {size} bytes exceeds limit of {MAX_FILE_SIZE_BYTES} bytes"
        )
    return issues


def check_command_output_size(size: int, command: str) -> list[str]:
    """Check if command output exceeds the limit.

    Args:
        size: Output size in bytes.
        command: Command string (for error messages).

    Returns:
        List of issue strings (empty if within limit).
    """
    issues: list[str] = []
    if size > MAX_COMMAND_OUTPUT_BYTES:
        issues.append(
            f"command '{command}' output {size} bytes "
            f"exceeds limit of {MAX_COMMAND_OUTPUT_BYTES} bytes"
        )
    return issues


def check_changeset_limits(changeset: "ChangeSet") -> list[str]:
    """Check ChangeSet limits.

    Args:
        changeset: The ChangeSet to validate.

    Returns:
        List of issue strings (empty if within limits).
    """

    issues: list[str] = []

    # Check number of changes
    if len(changeset.changes) > MAX_CHANGES_PER_CHANGESET:
        issues.append(
            f"ChangeSet has {len(changeset.changes)} changes, "
            f"exceeds limit of {MAX_CHANGES_PER_CHANGESET}"
        )

    # Check total content size
    total_content = sum(len(fc.content or "") for fc in changeset.changes)
    if total_content > MAX_TOTAL_CONTENT_BYTES:
        issues.append(
            f"ChangeSet total content size {total_content} bytes "
            f"exceeds limit of {MAX_TOTAL_CONTENT_BYTES} bytes"
        )

    return issues
