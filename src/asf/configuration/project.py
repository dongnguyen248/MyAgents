from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from asf.configuration.platform import ConfigModel


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
