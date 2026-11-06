from __future__ import annotations

from pathlib import Path
from typing import Any

from asf.agents.base import AgentRuntime
from asf.agents.implement.agent import ImplementAgent, ImplementSettings
from asf.configuration.platform import PlatformConfig
from asf.tools.ports import RepositoryPort

__all__ = ["build_implement_agent"]


def build_implement_agent(
    runtime: AgentRuntime,
    platform: PlatformConfig,
    templates_dir: Path,
    repository: RepositoryPort,
) -> ImplementAgent:
    """Builds a configured ImplementAgent instance."""
    from asf.agents.loading import load_implement_prompts

    prompts = load_implement_prompts()

    agent_cfg = platform.agents.get("implement")
    model: str | None = None
    parameters: dict[str, Any] = {}

    if agent_cfg and agent_cfg.model_profile:
        profile = platform.models.profiles.get(agent_cfg.model_profile)
        if profile:
            model = profile.model
            parameters = dict(profile.parameters)

    settings = agent_cfg.settings if agent_cfg else {}
    return ImplementAgent(
        runtime,
        repository,
        ImplementSettings(
            prompts=prompts,
            model=model,
            parameters=parameters,
            edit_format=settings.get("editFormat", "blocks"),
            repair_attempts=settings.get("repairAttempts", 1),
            repo_map_max_chars=settings.get("repoMapMaxChars", 6000),
        ),
    )
