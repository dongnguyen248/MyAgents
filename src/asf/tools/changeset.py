from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = ["FileChange", "ChangeSet"]


class FileChange(BaseModel):
    """A single file change in a change set."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    path: str = Field(..., min_length=1, alias="path")
    operation: Literal["create", "modify", "delete"] = Field(..., alias="operation")
    content: str | None = Field(default=None, alias="content")

    @field_validator("content", mode="after")
    @classmethod
    def validate_content_rules(cls, v: str | None, info) -> str | None:
        operation = info.data.get("operation")
        if operation in ("create", "modify"):
            if v is None:
                raise ValueError(f"{operation} operation requires 'content'")
            if "\x00" in v:
                raise ValueError("content must not contain NUL bytes")
        elif operation == "delete":
            if v is not None:
                raise ValueError("delete operation must not have 'content'")
        return v


class ChangeSet(BaseModel):
    """A complete set of file changes for a task."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    changes: list[FileChange] = Field(default_factory=list, alias="changes")

    @field_validator("changes", mode="after")
    @classmethod
    def validate_no_duplicate_paths(cls, v: list[FileChange]) -> list[FileChange]:
        paths = [fc.path for fc in v]
        if len(paths) != len(set(paths)):
            raise ValueError("ChangeSet contains duplicate paths")
        return v