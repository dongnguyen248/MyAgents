from __future__ import annotations

from pathlib import Path
from typing import Any

from asf.agents.base import AgentRuntime
from asf.agents.task.agent import TaskAgent
from asf.configuration.platform import PlatformConfig

__all__ = ["build_task_agent"]


def build_task_agent(
    runtime: AgentRuntime,
    platform: PlatformConfig,
    templates_dir: Path,
) -> TaskAgent:
    """Builds a configured TaskAgent instance."""
    from asf.agents.loading import load_task_prompts, load_task_template

    prompts = load_task_prompts()
    template = load_task_template(templates_dir)

    agent_cfg = platform.agents.get("task")
    model: str | None = None
    parameters: dict[str, Any] = {}

    if agent_cfg and agent_cfg.model_profile:
        profile = platform.models.profiles.get(agent_cfg.model_profile)
        if profile:
            model = profile.model
            parameters = dict(profile.parameters)

    return TaskAgent(
        runtime,
        prompts=prompts,
        template=template,
        model=model,
        parameters=parameters,
    )
