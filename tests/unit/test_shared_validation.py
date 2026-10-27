from __future__ import annotations

from asf.agents._shared.validation import (
    reject_whitespace_only,
    validate_list_no_whitespace,
    validate_no_duplicates,
)


def test_reject_whitespace_only_valid_string() -> None:
    assert reject_whitespace_only("hello", "field") == []
    assert reject_whitespace_only(" hello ", "field") == []


def test_reject_whitespace_only_empty_string() -> None:
    assert reject_whitespace_only("", "field") == [
        "field: must not be empty or whitespace-only"
    ]


def test_reject_whitespace_only_whitespace_only() -> None:
    assert reject_whitespace_only("   ", "field") == [
        "field: must not be empty or whitespace-only"
    ]
    assert reject_whitespace_only("\t\n", "field") == [
        "field: must not be empty or whitespace-only"
    ]


def test_validate_no_duplicates_no_duplicates() -> None:
    assert validate_no_duplicates(["a", "b", "c"], "field") == []


def test_validate_no_duplicates_with_duplicates() -> None:
    issues = validate_no_duplicates(["a", "b", "a", "c", "b"], "field")
    assert len(issues) == 1
    assert "duplicate values" in issues[0]
    assert "a" in issues[0]
    assert "b" in issues[0]


def test_validate_no_duplicates_empty_list() -> None:
    assert validate_no_duplicates([], "field") == []


def test_validate_list_no_whitespace_valid_list() -> None:
    assert validate_list_no_whitespace(["a", "b", "c"], "field") == []


def test_validate_list_no_whitespace_empty_item() -> None:
    issues = validate_list_no_whitespace(["a", "", "c"], "field")
    assert len(issues) == 1
    assert "field[1]" in issues[0]


def test_validate_list_no_whitespace_whitespace_item() -> None:
    issues = validate_list_no_whitespace(["a", "  ", "c"], "field")
    assert len(issues) == 1
    assert "field[1]" in issues[0]