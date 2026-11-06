"""Tests for HarnessComponents, assembly and fingerprinting (Phase 11b, H1)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from asf.agents._shared.harness import (
    HarnessComponents,
    agent_skills_section,
    assemble_base_prompt,
    components_from_prompts,
    fingerprint,
    guardrails_memory_section,
)
from asf.agents.base import AgentRuntime
from asf.agents.loading import load_spec_prompts, load_spec_template
from asf.agents.spec.agent import SpecAgent, SpecSettings
from asf.contracts.models import AgentRequest
from asf.models.fake import ScriptedModelGateway

REPO_ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 11, 2, tzinfo=UTC)

BASE = HarnessComponents(contract="C:", system="S:", revision="R:")


def test_fingerprint_is_stable_and_component_sensitive():
    assert fingerprint(BASE) == fingerprint(
        HarnessComponents(contract="C:", system="S:", revision="R:")
    )
    variants = [
        HarnessComponents(contract="X", system="S:", revision="R:"),
        HarnessComponents(contract="C:", system="X", revision="R:"),
        HarnessComponents(contract="C:", system="S:", revision="X"),
        HarnessComponents(contract="C:", system="S:", revision="R:", guardrails="G"),
        HarnessComponents(contract="C:", system="S:", revision="R:", memory="M"),
        HarnessComponents(contract="C:", system="S:", revision="R:", tool_guidance="T"),
        HarnessComponents(contract="C:", system="S:", revision="R:", skills={"a": "A"}),
    ]
    for variant in variants:
        assert fingerprint(variant) != fingerprint(BASE)


def test_fingerprint_ignores_skill_mapping_order():
    left = HarnessComponents(skills={"a": "1", "b": "2"})
    right = HarnessComponents(skills={"b": "2", "a": "1"})
    assert fingerprint(left) == fingerprint(right)


def test_assemble_base_prompt_with_and_without_revision():
    assert assemble_base_prompt(BASE) == "C:S:"
    assert assemble_base_prompt(BASE, revision=True) == "C:S:\n\nR:"


def test_new_sections_are_empty_when_components_are_empty():
    assert guardrails_memory_section(BASE) == ""
    assert agent_skills_section(BASE) == ""


def test_new_sections_render_in_order():
    components = HarnessComponents(
        guardrails="Be careful.",
        memory="Remember this.",
        skills={"zeta": "Z body", "alpha": "A body"},
    )
    assert guardrails_memory_section(components) == "\n\nBe careful.\n\nRemember this."
    assert (
        agent_skills_section(components)
        == "\n\n### Skill: alpha\nA body\n\n### Skill: zeta\nZ body"
    )


def _spec_agent(gateway: ScriptedModelGateway, harness: HarnessComponents | None) -> SpecAgent:
    runtime = AgentRuntime(models=gateway, clock=lambda: NOW, new_id=lambda: "gen-1")
    settings = SpecSettings(
        prompts=load_spec_prompts(),
        template=load_spec_template(REPO_ROOT / "templates"),
        model="test-model",
        harness=harness,
    )
    return SpecAgent(runtime, settings)


def _spec_request() -> AgentRequest:
    return AgentRequest(
        request_id="req-1",
        task_id="task-1",
        project_id="proj-1",
        workflow_id="software-development",
        agent_id="agent-spec",
        input={"requirement": "Build a calculator", "language": "en"},
        context={},
        artifacts=[],
        feedback=[],
        metadata={"attempt": 1},
    )


def _valid_spec_reply() -> str:
    template = load_spec_template(REPO_ROOT / "templates")
    lines = ["# SPEC: Calculator"]
    for section in template.required_sections:
        lines.append(section)
        lines.append("Content.")
    return "\n\n".join(lines)


def test_spec_agent_stamps_default_harness_fingerprint():
    gateway = ScriptedModelGateway([_valid_spec_reply()])
    agent = _spec_agent(gateway, None)
    result = agent.execute(_spec_request())
    assert result.status == "SUCCESS", result.errors
    prompts = load_spec_prompts()
    expected = fingerprint(
        components_from_prompts(
            contract=prompts.contract,
            system=prompts.system,
            revision=prompts.revision,
        )
    )
    assert result.artifacts[0].metadata["harnessFingerprint"] == expected


def test_spec_agent_stamps_override_and_uses_its_guardrails():
    custom = HarnessComponents(
        contract="CONTRACT TEXT. ",
        system="System text.",
        revision="Revision text.",
        guardrails="GUARDRAIL SENTINEL",
    )
    gateway = ScriptedModelGateway([_valid_spec_reply()])
    agent = _spec_agent(gateway, custom)
    result = agent.execute(_spec_request())
    assert result.status == "SUCCESS", result.errors
    assert result.artifacts[0].metadata["harnessFingerprint"] == fingerprint(custom)
    system_message = gateway.requests[0].messages[0].content
    assert system_message.startswith("CONTRACT TEXT. System text.")
    assert "GUARDRAIL SENTINEL" in system_message
