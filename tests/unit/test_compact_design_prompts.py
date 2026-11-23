"""Unit tests for compact design prompts, stack filtering, rules sections, and skill digests."""

from __future__ import annotations

import logging
from pathlib import Path

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


def test_stack_detection_priority(caplog):
    caplog.set_level(logging.INFO)
    tech = {"backend": ["python"], "frontend": ["react", "typescript"]}

    # (a) metadata language=python, requirement has no signals -> stack python, log from metadata
    caplog.clear()
    detected_a = detect_task_stack("python", tech, text_signal="do something generic", files=[])
    assert detected_a == frozenset({"python"})
    assert "Stack detected from metadata: python" in caplog.text

    # (b) metadata language conflicts with text signal -> metadata wins
    caplog.clear()
    detected_b = detect_task_stack(
        "python", tech, text_signal="Build a React component with App.tsx", files=["App.tsx"]
    )
    assert detected_b == frozenset({"python"})
    assert "Stack detected from metadata: python" in caplog.text

    # Priority 2: intersection of project stack with signals
    detected_sig = detect_task_stack(
        None, tech, text_signal="Run pytest on tests/test_calc.py", files=["calc.py"]
    )
    assert detected_sig == frozenset({"python"})

    # Union when multiple stacks detected in signals
    detected_multi = detect_task_stack(None, tech, text_signal="test", files=["calc.py", "App.tsx"])
    assert detected_multi == frozenset({"python", "typescript"})

    # (c) Priority 3: empty signals / unknown stack -> returns empty frozenset, logs unknown
    caplog.clear()
    unknown = detect_task_stack(None, tech, text_signal="no signals here", files=[])
    assert unknown == frozenset()
    assert "Stack unknown for task; omitting language rule packs" in caplog.text


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


def test_rules_typescript_react_positive_filtering(caplog):
    caplog.set_level(logging.WARNING)
    ts_rules = (
        "<!-- stack: typescript -->\n# TypeScript and React Standards\n\n"
        "## API Contract and DTOs\nExport explicit DTO types for endpoints.\n\n"
        "## Security and Authorization\nValidate tokens and object-level permissions.\n\n"
        "## Component Structure\nGroup components by feature folder.\n\n"
        "## Naming Conventions\nUse PascalCase for components and camelCase for hooks.\n\n"
        "## Prettier and Formatting\nUse 2 spaces and no semicolons.\n\n"
        "## Test Style Guidelines\nUse Jest and RTL.\n\n"
        "## Extended Structure Details\n<!-- tags: structure -->\n"
        + ("Extra component architecture details for budget test. " * 60)
    )
    filtered = filter_rules_for_task(
        ts_rules, agent="spec", stack=frozenset({"typescript"}), budget=2500
    )
    # (a) API, security, structure, naming are loaded
    assert "## API Contract and DTOs" in filtered
    assert "## Security and Authorization" in filtered
    assert "## Component Structure" in filtered
    assert "## Naming Conventions" in filtered
    # (b) Formatting and test style are NOT loaded
    assert "Prettier and Formatting" not in filtered
    assert "Test Style Guidelines" not in filtered
    # (c) Budget <= 2500 chars and dropped section is logged
    assert len(filtered) <= 2500
    assert "omitted from agent 'spec': exceeded character budget" in caplog.text


def test_rules_python_positive_loading():
    py_rules = (
        "<!-- stack: python -->\n# Python Standards\n\n"
        "## API Models and Schemas\nUse Pydantic models for request bodies.\n\n"
        "## Security Policies\nEnforce object-level authorization checks.\n"
    )
    filtered = filter_rules_for_task(
        py_rules, agent="spec", stack=frozenset({"python"}), budget=2500
    )
    assert "## API Models and Schemas" in filtered
    assert "Use Pydantic models" in filtered
    assert "## Security Policies" in filtered
    assert "Enforce object-level authorization checks" in filtered


def test_rules_budget_enforcement_and_logging(caplog):
    caplog.set_level(logging.WARNING)
    long_section = "## 1. API Contract\n" + ("x" * 2000)
    second_section = "## 2. Security\n" + ("y" * 1000)
    rules_text = long_section + "\n\n" + second_section

    # With budget=2500, the second section cannot fit (2000 + 1000 > 2500)
    # The entire second section is dropped without cutting mid-sentence
    filtered = filter_rules_for_task(
        rules_text, agent="spec", stack=frozenset({"all"}), budget=2500
    )
    assert "## 1. API Contract" in filtered
    assert "## 2. Security" not in filtered
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


def test_runtime_pipeline_stack_and_standards(tmp_path):
    """Verifies runtime behavior via DemoFactoryService context building."""
    from asf.agents.loading import load_spec_prompts, load_spec_template
    from asf.api.demo import DemoFactoryService

    # Setup demo service with myagent profile
    demo = DemoFactoryService.__new__(DemoFactoryService)
    demo._max_review_rounds = None
    demo._projects_dir = tmp_path
    demo._skills_dir = tmp_path / "skills"
    demo._skills_dir.mkdir(parents=True, exist_ok=True)
    templates_dir = Path("templates")

    # (a) project có technology + task TS -> standards khác rỗng, chỉ có section đúng nhãn, <= trần
    ts_file = tmp_path / "rules" / "languages" / "typescript.md"
    ts_file.parent.mkdir(parents=True, exist_ok=True)
    ts_file.write_text(
        "<!-- stack: typescript -->\n# TS Rules\n\n"
        "## API DTO\nDefine explicit DTOs.\n\n"
        "## Security Auth\nEnforce object permissions.\n\n"
        "## Formatting\nUse 2 spaces.\n",
        encoding="utf-8",
    )
    demo._projects = {"myagent": {"technologies": ["typescript", "react"]}}
    demo._project_profiles = {
        "myagent": {
            "technology": {"frontend": ["react", "typescript"], "backend": ["python"]},
            "enabledSkills": [],
        }
    }
    demo._STEP_DEFAULTS = {}
    demo._default_test_commands = lambda pid: [["pytest"]]

    from unittest.mock import patch

    def mock_start(self, tid, pid, inputs=None, context=None):
        return context

    with patch.object(DemoFactoryService.__bases__[0], "start_run", mock_start):
        ctx_ts = demo.start_run(
            "t-ts",
            "myagent",
            inputs={"spec": {"requirement": "Create CreateBiddingForm.tsx with React"}},
        )["project"]

    assert "technology" in ctx_ts

    spec_ctx_ts = SpecPromptContext(
        prompts=load_spec_prompts(),
        template=load_spec_template(templates_dir),
        requirement="Create CreateBiddingForm.tsx with React",
        language=None,
        project_context=ctx_ts,
    )
    msgs_ts = build_spec_messages(spec_ctx_ts)
    assert "## API DTO" in msgs_ts[0].content
    assert "## Security Auth" in msgs_ts[0].content
    assert "Formatting" not in msgs_ts[0].content
    assert len(msgs_ts[0].content) <= 3000
    # Project context in user message contains ONLY frontend
    assert "frontend" in msgs_ts[1].content
    assert "backend" not in msgs_ts[1].content

    # (b) project has technology + python task -> standards empty, context has no react/typescript
    spec_ctx_py = SpecPromptContext(
        prompts=load_spec_prompts(),
        template=load_spec_template(templates_dir),
        requirement="Build word count with pytest in calc.py",
        language=None,
        project_context=ctx_ts,
    )
    msgs_py = build_spec_messages(spec_ctx_py)
    # TS standards are omitted
    assert "TS Rules" not in msgs_py[0].content
    assert "## API DTO" not in msgs_py[0].content
    # Project context has python, NOT react/typescript
    assert "react" not in msgs_py[1].content
    assert "typescript" not in msgs_py[1].content
    assert "backend" in msgs_py[1].content

    # (b2) project has technology + task with NO signals -> context empty, standards empty
    spec_ctx_nosig = SpecPromptContext(
        prompts=load_spec_prompts(),
        template=load_spec_template(templates_dir),
        requirement="Do a generic task without any code or files",
        language=None,
        project_context=ctx_ts,
    )
    msgs_nosig = build_spec_messages(spec_ctx_nosig)
    assert "Project standards" not in msgs_nosig[0].content
    assert "technology" not in msgs_nosig[1].content

    # (c) project không khai báo technology -> stack unknown, standards rỗng
    demo._project_profiles["no_tech"] = {"enabledSkills": []}
    demo._projects["no_tech"] = {}
    with patch.object(DemoFactoryService.__bases__[0], "start_run", mock_start):
        res_none = demo.start_run(
            "t-none",
            "no_tech",
            inputs={"spec": {"requirement": "Build task"}},
        )
        ctx_no_tech = res_none["project"]
    spec_ctx_none = SpecPromptContext(
        prompts=load_spec_prompts(),
        template=load_spec_template(templates_dir),
        requirement="Build task with calc.py",
        language=None,
        project_context=ctx_no_tech,
    )
    msgs_none = build_spec_messages(spec_ctx_none)
    assert "Project standards" not in msgs_none[0].content

    # (d) language="vi" không bị coi là stack kỹ thuật
    spec_ctx_vi = SpecPromptContext(
        prompts=load_spec_prompts(),
        template=load_spec_template(templates_dir),
        requirement="Create CreateBiddingForm.tsx with React",
        language="vi",
        project_context=ctx_ts,
    )
    msgs_vi = build_spec_messages(spec_ctx_vi)
    assert "## Output language\nvi" in msgs_vi[1].content
    assert "## API DTO" in msgs_vi[0].content
