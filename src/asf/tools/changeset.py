from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = ["FileChange", "ChangeSet"]


class FileChange(BaseModel):
    """A single file change in a change set."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    path: str = Field(..., min_length=1, alias="path")
    operation: Literal["create", "modify", "delete"] = Field(..., alias="operation")
    content: str | None = Field(default=None, alias="content")

    @model_validator(mode="after")
    def validate_content_rules(self) -> "FileChange":
        """Validate content rules per D12/D9:
        - create/modify require non-None content
        - delete forbids content
        - no NUL bytes in content
        """
        operation = self.operation
        content = self.content

        if operation in ("create", "modify"):
            if content is None:
                raise ValueError(f"{operation} operation requires 'content'")
            if "\x00" in content:
                raise ValueError("content must not contain NUL bytes")
        elif operation == "delete":
            if content is not None:
                raise ValueError("delete operation must not have 'content'")
        return self


class ChangeSet(BaseModel):
    """A complete set of file changes for a task."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    changes: list[FileChange] = Field(..., alias="changes", min_length=1, max_length=50)

    @model_validator(mode="after")
    def validate_no_duplicate_paths(self) -> "ChangeSet":
        paths = [fc.path for fc in self.changes]
        if len(paths) != len(set(paths)):
            raise ValueError("ChangeSet contains duplicate paths")
        return self
