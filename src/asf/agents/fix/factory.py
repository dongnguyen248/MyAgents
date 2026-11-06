from __future__ import annotations

from pathlib import Path

from asf.agents.base import AgentRuntime
from asf.agents.fix.agent import FixAgent, FixSettings
from asf.configuration.platform import PlatformConfig
from asf.tools.ports import RepositoryPort


def build_fix_agent(
    runtime: AgentRuntime,
    platform: PlatformConfig,
    templates_dir: Path,
    repository: RepositoryPort,
) -> FixAgent:
    from asf.agents.loading import load_fix_prompts

    config = platform.agents.get("fix")
    profile = (
        platform.models.profiles.get(config.model_profile)
        if config is not None and config.model_profile
        else None
    )
    settings = config.settings if config is not None else {}
    return FixAgent(
        runtime,
        repository,
        FixSettings(
            prompts=load_fix_prompts(),
            model=profile.model if profile else None,
            parameters=profile.parameters if profile else {},
            edit_format=settings.get("editFormat", "blocks"),
            repair_attempts=settings.get("repairAttempts", 1),
            repo_map_max_chars=settings.get("repoMapMaxChars", 6000),
            report_tail_lines=settings.get("reportTailLines", 120),
        ),
    )
