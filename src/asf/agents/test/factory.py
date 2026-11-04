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
    return TestAgent(runtime, sandbox)
