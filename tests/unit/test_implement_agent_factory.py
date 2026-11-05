"""Tests for ImplementAgent factory and loading."""

from __future__ import annotations

from pathlib import Path

from asf.agents.base import AgentRuntime
from asf.agents.implement.agent import ImplementAgent
from asf.agents.implement.factory import build_implement_agent
from asf.agents.implement.prompts import ImplementPrompts
from asf.agents.loading import load_implement_prompts
from asf.configuration.platform import PlatformConfig
from asf.models.fake import ScriptedModelGateway
from asf.tools.fake import InMemoryRepository
from tests.unit.implement_helpers import T_AWARE, make_valid_changeset_reply


def test_factory_creates_agent_with_repository() -> None:
    """Factory builds an agent with injected repository via platform config."""
    gateway = ScriptedModelGateway([make_valid_changeset_reply()])
    runtime = AgentRuntime(models=gateway, clock=lambda: T_AWARE, new_id=lambda: "id-1")
    repo = InMemoryRepository()

    # Minimal platform config
    platform = PlatformConfig(
        models={"profiles": {}},
        agents={"implement": {"model_profile": None}},
    )
    templates_dir = Path(__file__).resolve().parents[2] / "templates"

    agent = build_implement_agent(runtime, platform, templates_dir, repo)

    assert isinstance(agent, ImplementAgent)
    assert agent._repository is repo
    assert agent._prompts is not None
    assert isinstance(agent._prompts, ImplementPrompts)


def test_factory_uses_platform_model_profile() -> None:
    """Factory uses model and parameters from platform config."""
    gateway = ScriptedModelGateway([make_valid_changeset_reply()])
    runtime = AgentRuntime(models=gateway, clock=lambda: T_AWARE, new_id=lambda: "id-1")
    repo = InMemoryRepository()

    platform = PlatformConfig(
        models={
            "profiles": {
                "test-profile": {
                    "provider": "test-provider",
                    "model": "test-model",
                    "parameters": {"temperature": 0.5},
                }
            }
        },
        agents={"implement": {"model_profile": "test-profile"}},
    )
    templates_dir = Path(__file__).resolve().parents[2] / "templates"

    agent = build_implement_agent(runtime, platform, templates_dir, repo)

    assert agent._model == "test-model"
    assert agent._parameters == {"temperature": 0.5}


def test_factory_requires_repository() -> None:
    """Factory requires repository parameter."""
    gateway = ScriptedModelGateway([make_valid_changeset_reply()])
    runtime = AgentRuntime(models=gateway, clock=lambda: T_AWARE, new_id=lambda: "id-1")
    platform = PlatformConfig(models={"profiles": {}}, agents={"implement": {}})
    templates_dir = Path(__file__).resolve().parents[2] / "templates"

    try:
        build_implement_agent(runtime, platform, templates_dir)
        assert False, "Should have raised TypeError"
    except TypeError:
        pass


def test_loading_loads_system_prompt() -> None:
    """load_implement_prompts loads system prompt from package."""
    prompts = load_implement_prompts()
    assert isinstance(prompts, ImplementPrompts)
    assert len(prompts.system) > 0


def test_loading_returns_non_empty_system_prompt() -> None:
    """load_implement_prompts returns non-empty system prompt."""
    prompts = load_implement_prompts()
    assert isinstance(prompts, ImplementPrompts)
    assert "Implement" in prompts.system


def test_direct_constructor_accepts_prompts_model_params() -> None:
    """ImplementAgent constructor accepts prompts, model, parameters directly."""
    gateway = ScriptedModelGateway([make_valid_changeset_reply()])
    runtime = AgentRuntime(models=gateway, clock=lambda: T_AWARE, new_id=lambda: "id-1")
    repo = InMemoryRepository()
    prompts = load_implement_prompts()
    model = "test-model"
    parameters = {"temperature": 0.5}

    agent = ImplementAgent(
        runtime,
        repo,
        prompts=prompts,
        model=model,
        parameters=parameters,
        edit_format="json",  # the scripted reply below is the legacy JSON format
        repair_attempts=0,
    )

    assert agent._model == model
    assert agent._parameters == parameters
    assert agent._prompts is prompts
