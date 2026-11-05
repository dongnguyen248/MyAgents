from __future__ import annotations

__all__ = [
    "reject_whitespace_only",
    "validate_no_duplicates",
    "validate_list_no_whitespace",
]


def reject_whitespace_only(value: str, field_name: str) -> list[str]:
    """Reject strings that are empty or whitespace-only.

    Args:
        value: The string to validate.
        field_name: Name of the field (for error messages).

    Returns:
        List of issue strings (empty if valid).
    """
    issues: list[str] = []
    if not value or not value.strip():
        issues.append(f"{field_name}: must not be empty or whitespace-only")
    return issues


def validate_no_duplicates(items: list[str], field_name: str) -> list[str]:
    """Validate that a list has no duplicate values.

    Args:
        items: The list to check.
        field_name: Name of the field (for error messages).

    Returns:
        List of issue strings (empty if no duplicates).
    """
    issues: list[str] = []
    seen: set[str] = set()
    duplicates: set[str] = set()
    for item in items:
        if item in seen:
            duplicates.add(item)
        seen.add(item)
    if duplicates:
        issues.append(f"{field_name}: duplicate values: {sorted(duplicates)}")
    return issues


def validate_list_no_whitespace(items: list[str], field_name: str) -> list[str]:
    """Validate that list items are not empty or whitespace-only.

    Args:
        items: The list to validate.
        field_name: Name of the field (for error messages).

    Returns:
        List of issue strings (empty if valid).
    """
    issues: list[str] = []
    for i, item in enumerate(items):
        if not item or not item.strip():
            issues.append(f"{field_name}[{i}]: must not be empty or whitespace-only")
    return issues
