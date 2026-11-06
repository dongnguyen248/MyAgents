from __future__ import annotations

from pathlib import Path
from typing import Any

from asf.agents.artifact_review.agent import ArtifactReviewAgent, ArtifactReviewSettings
from asf.agents.base import AgentRuntime
from asf.configuration.platform import PlatformConfig

__all__ = ["build_artifact_review_agent"]


def build_artifact_review_agent(
    runtime: AgentRuntime, platform: PlatformConfig, templates_dir: Path
) -> ArtifactReviewAgent:
    """Build the artifact reviewer with its configured model profile."""
    from asf.agents.loading import load_artifact_review_prompts

    config = platform.agents.get("artifact-review")
    model: str | None = None
    parameters: dict[str, Any] = {}
    if config and config.model_profile:
        profile = platform.models.profiles.get(config.model_profile)
        if profile:
            model = profile.model
            parameters = dict(profile.parameters)
    settings = config.settings if config else {}
    return ArtifactReviewAgent(
        runtime,
        ArtifactReviewSettings(
            prompts=load_artifact_review_prompts(),
            model=model,
            parameters=parameters,
            max_tasks=settings.get("maxTasks", 50),
            model_profile=config.model_profile if config else None,
        ),
    )
