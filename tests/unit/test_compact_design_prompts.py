"""Unit tests for compact design prompts, stack filtering, rules sections, and skill digests."""

from __future__ import annotations

import logging

from asf.agents._shared.design_prompts import (
    build_design_user_content,
    format_language_section,
)
from asf.agents._shared.rules import (
    detect_task_stack,
    filter_rules_for_task,
)
from asf.agents._shared.skills import skills_for_agent
from asf.agents.spec.agent import _build_retry_messages
from asf.agents.spec.prompts import (
    SpecPromptContext,
    SpecPrompts,
    SpecTemplate,
    build_spec_messages,
)
from asf.contracts.models import ModelMessage

# Fixed test fixtures (do not depend on disk files)
FIXTURE_RULES = """<!-- stack: typescript -->
# TypeScript and React Rules
## 1. General Principles
Write clean code.

## 2. API Contract
Follow strict DTO contract.

## 3. Formatting and Linting
Use 2 spaces and prettier.

<!-- stack: python -->
# Python Rules
## 1. Architecture Structure
Organize packages with explicit public exports.

## 2. Security and Permissions
Validate authentication tokens and check permissions on object level.

## 3. Code Style and Whitespace
Never leave trailing whitespace. Max 100 characters per line.
"""

FIXTURE_SKILLS = [
    {
        "id": "security",
        "content": "Full security body for implement/fix agents...",
        "digest": "Explicitly define authorization, data sensitivity, and auditing.",
    },
    {
        "id": "react",
        "content": "Full react body...",
        "digest": "Use functional components and hooks.",
    },
    {
        "id": "python",
        "content": "Full python body...",
        "digest": "Use type hints and pytest conventions.",
    },
    {
        "id": "general",
        "content": "Full general body without digest...",
    },
]


def test_stack_detection_priority():
    # Priority 1: metadata language
    tech = {"backend": ["python"], "frontend": ["react"]}
    assert detect_task_stack("python", tech) == frozenset({"python"})
    assert detect_task_stack("typescript", tech) == frozenset({"typescript"})

    # Priority 2: intersection of project stack with signals
    detected = detect_task_stack(
        None, tech, text_signal="Run pytest on tests/test_calc.py", files=["calc.py"]
    )
    assert detected == frozenset({"python"})

    # Union when multiple stacks detected in signals
    detected_multi = detect_task_stack(None, tech, text_signal="test", files=["calc.py", "App.tsx"])
    assert detected_multi == frozenset({"python", "typescript"})

    # Priority 3: unknown stack -> returns empty frozenset (omits language packs)
    unknown = detect_task_stack(None, tech, text_signal="no signals here", files=[])
    assert unknown == frozenset()


def test_rules_stack_filtering_and_formatting_omission():
    # When task stack is python, typescript rules are omitted
    filtered = filter_rules_for_task(FIXTURE_RULES, agent="spec", stack=frozenset({"python"}))
    assert "TypeScript" not in filtered
    assert "prettier" not in filtered
    # Formatting section is dropped even within python rules
    assert "Whitespace" not in filtered
    assert "trailing whitespace" not in filtered
    # Security section is retained
    assert "Security and Permissions" in filtered


def test_rules_budget_enforcement_and_logging(caplog):
    caplog.set_level(logging.WARNING)
    long_section = "## 1. Security\n" + ("x" * 2000)
    second_section = "## 2. API\n" + ("y" * 1000)
    rules_text = long_section + "\n\n" + second_section

    # With budget=2500, the second section cannot fit (2000 + 1000 > 2500)
    # The entire second section is dropped without cutting mid-sentence
    filtered = filter_rules_for_task(
        rules_text, agent="spec", stack=frozenset({"all"}), budget=2500
    )
    assert "## 1. Security" in filtered
    assert "## 2. API" not in filtered
    assert len(filtered) <= 2500
    assert "omitted from agent 'spec': exceeded character budget" in caplog.text


def test_skill_digest_and_stack_filtering(caplog):
    caplog.set_level(logging.WARNING)
    project = {
        "skills": FIXTURE_SKILLS,
        "enabledSkills": ["security", "react", "python", "general"],
    }
    # Design agent (spec) with python stack:
    # 1. 'security' has digest -> included
    # 2. 'react' requires typescript, task is python -> omitted by stack
    # 3. 'python' not in SKILL_AGENTS for spec -> omitted
    # 4. 'general' has NO digest -> omitted and warning logged
    skills = skills_for_agent(project, agent="spec", stack=frozenset({"python"}))
    skill_ids = [s[0] for s in skills]
    assert "security" in skill_ids
    assert "react" not in skill_ids
    assert "general" not in skill_ids
    assert "Skill 'general' has no digest; omitting from design agent 'spec'" in caplog.text

    # Code agent (implement) receives full content, not digest
    impl_skills = skills_for_agent(project, agent="implement", stack=frozenset({"python"}))
    sec_content = next(c for sid, c in impl_skills if sid == "security")
    assert "Full security body" in sec_content


def test_output_language_branching():
    # Branch 1: language is None -> omitted from user message
    user_no_lang = build_design_user_content(
        ["## Requirement\nTest", format_language_section(None)]
    )
    assert "## Output language" not in user_no_lang

    # Branch 2: language is explicit -> included
    user_lang = build_design_user_content(["## Requirement\nTest", format_language_section("vi")])
    assert "## Output language\nvi" in user_lang


def test_contract_uniqueness_and_markers():
    prompts = SpecPrompts(
        system="System prompt body",
        revision="Revision body",
        contract="Contract body",
    )
    template = SpecTemplate(
        text="# SPEC: title\n## Background / Goal\n## Scope (in / out)",
        required_sections=["## Background / Goal", "## Scope (in / out)"],
    )
    ctx = SpecPromptContext(
        prompts=prompts,
        template=template,
        requirement="Do something",
        language=None,
        project_context={"name": "TestProj"},
    )
    msgs = build_spec_messages(ctx)
    full_prompt = msgs[0].content + "\n\n" + msgs[1].content

    # Heading markers live in template (user message), not duplicated in system prompt
    assert full_prompt.count("## Background / Goal") == 1
    assert full_prompt.count("## Scope (in / out)") == 1
    assert "## Background / Goal" not in msgs[0].content


def test_clean_retry_history():
    initial_msgs = [
        ModelMessage(role="system", content="System instruction"),
        ModelMessage(role="user", content="User requirement"),
    ]
    missing = ["## Background / Goal", "## Acceptance criteria"]
    retry_msgs = _build_retry_messages(initial_msgs, missing)

    # Retry messages must NOT contain an assistant turn
    roles = [m.role for m in retry_msgs]
    assert roles == ["system", "user"]
    assert "assistant" not in roles
    # User message contains original content plus the clean retry note
    assert "User requirement" in retry_msgs[1].content
    expected_note = (
        "Previous attempt omitted required template section(s):"
        " ## Background / Goal, ## Acceptance criteria"
    )
    assert expected_note in retry_msgs[1].content
    assert "Never ask questions" in retry_msgs[1].content
