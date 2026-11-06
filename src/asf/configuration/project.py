from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import Field

from asf.configuration.platform import ConfigModel

#: How a project's local folder (``repository.path``) is used by runs:
#: ``direct`` — agents edit the folder itself, protected by the undo
#: journal; ``worktree`` — each run gets its own git worktree (a non-git
#: folder falls back to direct with a warning); ``auto`` — worktree for
#: git folders, direct for the rest (the historical behaviour).
WORKSPACE_MODES = ("direct", "worktree", "auto")

#: Profiles that do not declare ``repository.workspaceMode`` keep the
#: historical behaviour; the key only steers local-folder use and has
#: no effect without ``repository.path``.
DEFAULT_WORKSPACE_MODE = "auto"

#: The mode a project created through the dashboard gets when its
#: profile payload does not declare one.
NEW_PROJECT_WORKSPACE_MODE = "direct"


def workspace_mode_of(repository: Mapping[str, Any]) -> str:
    """The validated ``repository.workspaceMode`` of a profile."""
    raw = repository.get("workspaceMode", DEFAULT_WORKSPACE_MODE)
    if raw not in WORKSPACE_MODES:
        raise ValueError(
            f"repository.workspaceMode must be one of {', '.join(WORKSPACE_MODES)}; got {raw!r}",
        )
    return str(raw)


def keep_changes_on_failure_of(repository: Mapping[str, Any]) -> bool:
    """The validated ``repository.keepChangesOnFailure`` of a profile.

    Direct mode only: when true, a FAILED or CANCELLED run leaves its
    files in the project folder instead of reverting the undo journal.
    """
    raw = repository.get("keepChangesOnFailure", False)
    if not isinstance(raw, bool):
        raise ValueError(
            f"repository.keepChangesOnFailure must be a boolean; got {raw!r}",
        )
    return raw


class ProjectProfile(ConfigModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = ""
    repository: dict[str, Any]
    technology: dict[str, Any]
    enabled_agents: list[str] = Field(default_factory=list)
    enabled_skills: list[str] = Field(default_factory=list)
    workflow: str = Field(min_length=1)
    configuration: dict[str, Any] = Field(default_factory=dict)
    status: Literal["ACTIVE", "INACTIVE", "ARCHIVED"] = "ACTIVE"

    def to_contract(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json")
