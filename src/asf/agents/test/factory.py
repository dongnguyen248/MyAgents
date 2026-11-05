from __future__ import annotations

from pathlib import Path

from asf.agents.base import AgentRuntime
from asf.agents.test.agent import TestAgent
from asf.configuration.platform import PlatformConfig
from asf.tools.ports import SandboxPort


def build_test_agent(
    runtime: AgentRuntime,
    platform: PlatformConfig,
    templates_dir: Path,
    sandbox: SandboxPort,
) -> TestAgent:
    """Build the deterministic runner without loading templates or model profiles."""
    config = platform.agents.get("test")
    settings = config.settings if config else {}
    return TestAgent(
        runtime, sandbox,
        fail_fast=bool(settings.get("failFast", True)),
    )
