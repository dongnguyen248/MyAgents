from __future__ import annotations

from pathlib import Path
from typing import Any

from asf.agents.base import AgentRuntime
from asf.agents.review.agent import ReviewAgent
from asf.configuration.platform import PlatformConfig

__all__ = ["build_review_agent"]


def build_review_agent(
    runtime: AgentRuntime, platform: PlatformConfig, templates_dir: Path
) -> ReviewAgent:
    """Build the reviewer with the configured model profile and packaged prompt."""
    from asf.agents.loading import load_review_prompts

    config = platform.agents.get("review")
    model: str | None = None
    parameters: dict[str, Any] = {}
    if config and config.model_profile:
        profile = platform.models.profiles.get(config.model_profile)
        if profile:
            model = profile.model
            parameters = dict(profile.parameters)
    settings = config.settings if config else {}
    return ReviewAgent(
        runtime,
        prompts=load_review_prompts(),
        model=model,
        parameters=parameters,
        skip_when_tests_pass=bool(settings.get("skipWhenTestsPass", False)),
        max_diff_lines=settings.get("maxDiffLines", 200),
        report_tail_lines=settings.get("reportTailLines", 120),
    )
