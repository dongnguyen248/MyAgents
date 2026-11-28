"""Agent skill selections as reported by dashboard query views."""

from typing import Any

from asf.agents._shared.skills import agent_skill_ids


def configured_agent_skills(service: Any, agent: str) -> list[str]:
    settings = getattr(service, "_agent_skill_settings", None)
    if settings is not None:
        return settings.selected(agent)
    return agent_skill_ids(agent)


def agent_skill_snapshot(service: Any) -> dict[str, list[str]]:
    settings = getattr(service, "_agent_skill_settings", None)
    return settings.snapshot() if settings is not None else {}
