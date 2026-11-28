"""Operator-selected skills per agent, persisted alongside model settings."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from threading import RLock
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from asf.agents._shared.skills import agent_skill_ids
from asf.api.skill_routes import list_skill_catalogue, skill_router

SUPPORTED_AGENTS = frozenset(
    {"spec", "plan", "task", "implement", "review", "fix", "artifact-review"}
)


class SkillSelection(BaseModel):
    skills: list[str]


class AgentSkillSettings:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._lock = RLock()
        self._overrides: dict[str, list[str]] = {}
        if path and path.is_file():
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or any(
                key not in SUPPORTED_AGENTS
                or not isinstance(value, list)
                or any(not isinstance(item, str) for item in value)
                for key, value in raw.items()
            ):
                raise ValueError("Invalid agent skill settings")
            self._overrides = raw

    def selected(self, agent: str) -> list[str]:
        return list(self._overrides.get(agent, agent_skill_ids(agent)))

    def snapshot(self) -> dict[str, list[str]]:
        return {agent: list(skills) for agent, skills in self._overrides.items()}

    def save(self, agent: str, skills: list[str]) -> None:
        with self._lock:
            updated = {**self._overrides, agent: sorted(set(skills))}
            if self._path:
                self._persist(updated)
            self._overrides = updated

    def _persist(self, updated: dict[str, list[str]]) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=self._path.parent, prefix=".agent-skills-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(updated, stream, indent=2)
                stream.write("\n")
            os.replace(name, self._path)
        finally:
            Path(name).unlink(missing_ok=True)


def _agent_type(service: Any, agent_id: str, kind: str = "Skill") -> str:
    agent = service.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    agent_type = str(agent["type"])
    if agent_id != f"agent-{agent_type}" or agent_type not in SUPPORTED_AGENTS:
        raise HTTPException(400, f"{kind} assignment is not supported for this agent")
    return agent_type


def agent_skill_router(service: Any, root: Path | None) -> APIRouter:
    directory = root if root is not None else Path(__file__).resolve().parents[3] / "skills"
    router = APIRouter()

    def settings() -> AgentSkillSettings:
        value = getattr(service, "_agent_skill_settings", None)
        if value is None:
            raise HTTPException(503, "Agent skill settings are unavailable")
        return value

    @router.get("/agents/{agent_id}/skills")
    def read_skills(agent_id: str) -> dict[str, list[str]]:
        return {"skills": settings().selected(_agent_type(service, agent_id))}

    @router.put("/agents/{agent_id}/skills")
    def save_skills(agent_id: str, body: SkillSelection) -> dict[str, list[str]]:
        agent = _agent_type(service, agent_id)
        available = {item["id"] for item in list_skill_catalogue(directory)}
        if set(body.skills) - available:
            raise HTTPException(422, "One or more skills are not in the catalogue")
        settings().save(agent, body.skills)
        return {"skills": settings().selected(agent)}

    return router


def register_agent_skill_routes(app: Any, service: Any) -> None:
    from asf.api.agent_rule_settings import rule_router

    root = getattr(service, "_skills_dir", None)
    app.include_router(skill_router(root, getattr(service, "_agent_skill_settings", None)))
    app.include_router(agent_skill_router(service, root))
    app.include_router(rule_router(service))
