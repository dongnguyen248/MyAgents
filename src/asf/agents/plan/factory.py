from __future__ import annotations

from pathlib import Path
from typing import Any

from asf.agents.base import AgentRuntime
from asf.agents.plan.agent import PlanAgent
from asf.configuration.platform import PlatformConfig

__all__ = ["build_plan_agent"]


def build_plan_agent(
    runtime: AgentRuntime,
    platform: PlatformConfig,
    templates_dir: Path,
) -> PlanAgent:
    """Builds a configured PlanAgent instance."""
    from asf.agents.loading import load_plan_prompts, load_plan_template

    prompts = load_plan_prompts()
    template = load_plan_template(templates_dir)

    agent_cfg = platform.agents.get("plan")
    model: str | None = None
    parameters: dict[str, Any] = {}

    if agent_cfg and agent_cfg.model_profile:
        profile = platform.models.profiles.get(agent_cfg.model_profile)
        if profile:
            model = profile.model
            parameters = dict(profile.parameters)

    return PlanAgent(
        runtime,
        prompts=prompts,
        template=template,
        model=model,
        parameters=parameters,
    )