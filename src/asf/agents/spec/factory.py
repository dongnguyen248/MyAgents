from __future__ import annotations

from pathlib import Path
from typing import Any

from asf.agents.base import AgentRuntime
from asf.agents.spec.agent import SpecAgent, SpecSettings
from asf.configuration.platform import PlatformConfig

__all__ = ["build_spec_agent"]


def build_spec_agent(
    runtime: AgentRuntime,
    platform: PlatformConfig,
    templates_dir: Path,
) -> SpecAgent:
    """Builds a configured SpecAgent instance."""
    from asf.agents.loading import load_spec_prompts, load_spec_template

    prompts = load_spec_prompts()
    template = load_spec_template(templates_dir)

    agent_cfg = platform.agents.get("spec")
    model: str | None = None
    parameters: dict[str, Any] = {}

    if agent_cfg and agent_cfg.model_profile:
        profile = platform.models.profiles.get(agent_cfg.model_profile)
        if profile:
            model = profile.model
            parameters = dict(profile.parameters)

    return SpecAgent(
        runtime,
        SpecSettings(prompts=prompts, template=template, model=model, parameters=parameters),
    )
