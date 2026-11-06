from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = ["TaskContent", "TaskItem"]


def _reject_whitespace_only(value: str, field_name: str) -> str:
    """Reject whitespace-only strings."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string (whitespace-only not allowed)")
    return value


def _validate_list_no_whitespace(v: list[str], field_name: str) -> list[str]:
    """Validate list items are non-empty strings (no whitespace-only)."""
    for item in v:
        if not isinstance(item, str) or not item.strip():
            msg = f"{field_name} items must be non-empty strings (whitespace-only not allowed)"
            raise ValueError(msg)
    return v


class TaskItem(BaseModel):
    """A single task item in the task list."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    id: str = Field(..., min_length=1, alias="id")
    title: str = Field(..., min_length=1, alias="title")
    milestone_ref: str = Field(..., min_length=1, alias="milestoneRef")
    description: str = Field(..., min_length=1, alias="description")
    acceptance_criteria: list[str] = Field(..., min_length=1, alias="acceptanceCriteria")
    depends_on: list[str] = Field(default_factory=list, alias="dependsOn")
    expected_files: list[str] = Field(default_factory=list, alias="expectedFiles")
    verification_hint: str = Field(..., min_length=1, alias="verificationHint")

    @field_validator("id")
    @classmethod
    def validate_id_format(cls, v: str) -> str:
        if not re.match(r"^T[1-9][0-9]*$", v):
            raise ValueError(f"Task ID '{v}' must match '^T[1-9][0-9]*$'")
        return v

    @field_validator("id", "title", "milestone_ref", "description", "verification_hint")
    @classmethod
    def validate_no_whitespace_strings(cls, v: str) -> str:
        return _reject_whitespace_only(v, "String field")

    @field_validator("acceptance_criteria", "depends_on", "expected_files", mode="before")
    @classmethod
    def ensure_list(cls, v: Any) -> list[str]:
        if not isinstance(v, list):
            raise ValueError("Must be a list")
        return v

    @field_validator("acceptance_criteria", "depends_on", "expected_files")
    @classmethod
    def validate_no_duplicates(cls, v: list[str]) -> list[str]:
        if len(v) != len(set(v)):
            raise ValueError("List contains duplicate entries")
        return v

    @field_validator("acceptance_criteria", "depends_on", "expected_files")
    @classmethod
    def validate_no_whitespace_strings_in_list(cls, v: list[str]) -> list[str]:
        return _validate_list_no_whitespace(v, "List field")


class TaskContent(BaseModel):
    """Full task output content."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    tasks: list[TaskItem] = Field(..., min_length=1, alias="tasks")
