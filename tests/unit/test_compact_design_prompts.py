"""Unit tests for compact design prompts, stack filtering, rules sections, and skill digests."""

from __future__ import annotations

import logging
from pathlib import Path

from asf.agents._shared.design_prompts import (
    build_design_user_content,
    format_language_section,
)
from asf.agents._shared.rules import (
    _document_stack,
    classify_section_scope,
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


def test_detect_stack_aliases_and_framework_signals(caplog):
    """Verifies framework signals (React, FastAPI) and alias mappings (ts -> typescript)."""
    caplog.set_level(logging.INFO)
    tech = {"backend": ["python", "fastapi"], "frontend": ["react", "typescript"]}

    # (1) Task only mentions "React component" without .tsx or "typescript" -> loads TS pack
    stack_react = detect_task_stack(
        None, tech, text_signal="Build a React component for bidding", files=[]
    )
    assert stack_react == frozenset({"typescript"})

    # (2) Explicit language="ts" alias -> loads TS pack
    stack_ts = detect_task_stack("ts", tech, text_signal="Build something", files=[])
    assert stack_ts == frozenset({"typescript"})

    # (3) Task only mentions "FastAPI" -> loads python pack
    stack_fastapi = detect_task_stack(
        None, tech, text_signal="Create FastAPI router endpoints", files=[]
    )
    assert stack_fastapi == frozenset({"python"})


def test_signal_detection_word_boundaries_and_false_positives():
    """Verifies word-boundary matching and false positive prevention."""
    tech_all = {
        "backend": ["python", "java", "csharp"],
        "frontend": ["react", "typescript"],
    }
    # False positives must NOT trigger any stack
    assert (
        detect_task_stack(None, tech_all, text_signal="Handle reaction results", files=[])
        == frozenset()
    )
    assert (
        detect_task_stack(
            None, {"backend": ["java"]}, text_signal="Write JavaScript module", files=[]
        )
        == frozenset()
    )
    assert (
        detect_task_stack(None, {"backend": ["java"]}, text_signal="Spring cleaning task", files=[])
        == frozenset()
    )

    # True positives including c# and .net and Spring Boot
    assert detect_task_stack(
        None, tech_all, text_signal="Build React component", files=[]
    ) == frozenset({"typescript"})
    assert detect_task_stack(
        None, tech_all, text_signal="Add FastAPI router", files=[]
    ) == frozenset({"python"})
    assert detect_task_stack(
        None, tech_all, text_signal="Create Spring Boot service", files=[]
    ) == frozenset({"java"})
    assert detect_task_stack(None, tech_all, text_signal="Build .NET API", files=[]) == frozenset(
        {"csharp"}
    )
    assert detect_task_stack(None, tech_all, text_signal="Add C# class", files=[]) == frozenset(
        {"csharp"}
    )


def test_unheaded_and_empty_rules_behavior(caplog):
    """Verifies the 4 rules-handling cases through build_spec_messages."""
    from asf.agents.loading import load_spec_prompts, load_spec_template

    prompts = load_spec_prompts()
    template = load_spec_template(Path("templates"))

    # 1. Unheaded <= 2500 -> loaded verbatim with INFO log
    caplog.clear()
    caplog.set_level(logging.INFO)
    short_rules = "Always validate inputs at API boundaries."
    msgs_short = build_spec_messages(
        SpecPromptContext(
            prompts=prompts,
            template=template,
            requirement="Generic task",
            language=None,
            project_context={"reviewRules": short_rules},
        )
    )
    assert short_rules in msgs_short[0].content
    assert "Project rules without headings loaded verbatim" in caplog.text

    # 2. Unheaded > 2500 -> omitted with WARNING stating dropped char count
    caplog.clear()
    caplog.set_level(logging.WARNING)
    long_rules = "Rule line. " * 260
    msgs_long = build_spec_messages(
        SpecPromptContext(
            prompts=prompts,
            template=template,
            requirement="Generic task",
            language=None,
            project_context={"reviewRules": long_rules},
        )
    )
    assert "Project standards" not in msgs_long[0].content
    assert f"{len(long_rules.strip())} chars exceed budget" in caplog.text

    # 3. Headed rules, no design-scope sections -> omitted with WARNING
    caplog.clear()
    non_design_rules = "## Formatting Rules\nUse 2 spaces.\n\n## Test Style\nUse pytest."
    msgs_non_design = build_spec_messages(
        SpecPromptContext(
            prompts=prompts,
            template=template,
            requirement="Generic task",
            language=None,
            project_context={"reviewRules": non_design_rules},
        )
    )
    assert "Project standards" not in msgs_non_design[0].content
    assert "no sections match design scopes" in caplog.text

    # 4. Project has no rules -> no warning
    caplog.clear()
    msgs_empty = build_spec_messages(
        SpecPromptContext(
            prompts=prompts,
            template=template,
            requirement="Generic task",
            language=None,
            project_context={"reviewRules": ""},
        )
    )
    assert "Project standards" not in msgs_empty[0].content
    assert not [
        r for r in caplog.records if r.levelno >= logging.WARNING and "rules" in r.message.lower()
    ]


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


def test_runtime_pipeline_ts_and_python_tasks(tmp_path):
    """Verifies runtime behavior via DemoFactoryService context building."""
    from unittest.mock import patch

    from asf.agents.loading import load_spec_prompts, load_spec_template
    from asf.api.demo import DemoFactoryService

    demo = DemoFactoryService.__new__(DemoFactoryService)
    demo._max_review_rounds = None
    demo._projects_dir = tmp_path
    demo._skills_dir = tmp_path / "skills"
    demo._skills_dir.mkdir(parents=True, exist_ok=True)
    templates_dir = Path("templates")

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
    assert "frontend" in msgs_ts[1].content
    assert "backend" not in msgs_ts[1].content

    spec_ctx_py = SpecPromptContext(
        prompts=load_spec_prompts(),
        template=load_spec_template(templates_dir),
        requirement="Build word count with pytest in calc.py",
        language=None,
        project_context=ctx_ts,
    )
    msgs_py = build_spec_messages(spec_ctx_py)
    assert "TS Rules" not in msgs_py[0].content
    assert "## API DTO" not in msgs_py[0].content
    assert "react" not in msgs_py[1].content
    assert "typescript" not in msgs_py[1].content
    assert "backend" in msgs_py[1].content


def test_runtime_pipeline_case_b_real_profile(caplog):
    """Case (b): real project profile with technology + task with no signals.

    Verifies demo.start_run context for Spec, Plan, Task omits rules & technology
    and logs 'Stack unknown for task; omitting language rule packs'.
    """
    from unittest.mock import patch

    from asf.agents.loading import (
        load_plan_prompts,
        load_plan_template,
        load_spec_prompts,
        load_spec_template,
        load_task_prompts,
        load_task_template,
    )
    from asf.agents.plan.prompts import PlanPromptContext, build_plan_messages
    from asf.agents.task.prompts import TaskPromptContext, build_task_messages
    from asf.api.demo import DemoFactoryService

    caplog.set_level(logging.WARNING)
    templates_dir = Path("templates")
    profile = {
        "id": "myagent",
        "name": "MyAgent",
        "technology": {"backend": ["python", "fastapi"], "frontend": ["react", "typescript"]},
        "enabledSkills": ["python", "react", "git", "testing", "security"],
    }

    demo = DemoFactoryService.__new__(DemoFactoryService)
    demo._max_review_rounds = None
    demo._projects_dir = Path("projects")
    demo._skills_dir = Path("skills")
    demo._projects = {"myagent": {"technologies": ["typescript", "react"]}}
    demo._project_profiles = {"myagent": profile}
    demo._STEP_DEFAULTS = {}
    demo._default_test_commands = lambda pid: [["pytest"]]

    def mock_start(self, tid, pid, inputs=None, context=None):
        return context

    with patch.object(DemoFactoryService.__bases__[0], "start_run", mock_start):
        res = demo.start_run(
            "t-nosig",
            "myagent",
            inputs={"spec": {"requirement": "Do generic task without any code or files"}},
        )
        ctx = res["project"]

    # 1. Spec Agent
    spec_ctx = SpecPromptContext(
        prompts=load_spec_prompts(),
        template=load_spec_template(templates_dir),
        requirement="Do generic task without any code or files",
        language=None,
        project_context=ctx,
    )
    msgs_spec = build_spec_messages(spec_ctx)
    assert "Project standards" not in msgs_spec[0].content
    assert "technology" not in msgs_spec[1].content

    # 2. Plan Agent
    plan_ctx = PlanPromptContext(
        prompts=load_plan_prompts(),
        template=load_plan_template(templates_dir),
        spec_artifact={
            "id": "spec-1",
            "version": "1",
            "content": {"text": "## Background / Goal\nGeneric"},
        },
        language=None,
        project_context=ctx,
    )
    msgs_plan = build_plan_messages(plan_ctx)
    assert "Project development rules" not in msgs_plan[0].content
    assert "technology" not in msgs_plan[1].content

    # 3. Task Agent
    task_ctx = TaskPromptContext(
        prompts=load_task_prompts(),
        template=load_task_template(templates_dir),
        spec_artifact={
            "id": "spec-1",
            "version": "1",
            "content": {"text": "## Background / Goal\nGeneric"},
        },
        plan_artifact={
            "id": "plan-1",
            "version": "1",
            "content": {"text": "## Milestones\nM1"},
        },
        language=None,
        project_context=ctx,
    )
    msgs_task = build_task_messages(task_ctx)
    assert "Project development rules" not in msgs_task[0].content
    assert "technology" not in msgs_task[1].content

    # 4. Assert log warning
    assert "Stack unknown for task; omitting language rule packs" in caplog.text


def test_runtime_pipeline_case_c_no_technology(tmp_path):
    """Case (c): project does not declare technology -> stack unknown."""
    from unittest.mock import patch

    from asf.agents.loading import load_spec_prompts, load_spec_template
    from asf.api.demo import DemoFactoryService

    demo = DemoFactoryService.__new__(DemoFactoryService)
    demo._max_review_rounds = None
    demo._projects_dir = tmp_path
    demo._skills_dir = tmp_path / "skills"
    demo._skills_dir.mkdir(parents=True, exist_ok=True)
    demo._projects = {"no_tech": {}}
    demo._project_profiles = {"no_tech": {"enabledSkills": []}}
    demo._STEP_DEFAULTS = {}
    demo._default_test_commands = lambda pid: [["pytest"]]

    def mock_start(self, tid, pid, inputs=None, context=None):
        return context

    with patch.object(DemoFactoryService.__bases__[0], "start_run", mock_start):
        res_none = demo.start_run(
            "t-none",
            "no_tech",
            inputs={"spec": {"requirement": "Build task"}},
        )
        ctx_no_tech = res_none["project"]
    spec_ctx_none = SpecPromptContext(
        prompts=load_spec_prompts(),
        template=load_spec_template(Path("templates")),
        requirement="Build task with calc.py",
        language=None,
        project_context=ctx_no_tech,
    )
    msgs_none = build_spec_messages(spec_ctx_none)
    assert "Project standards" not in msgs_none[0].content


def test_explicit_language_overrides_project_technology(caplog):
    """Priority 1: explicit language in metadata overrides project technology declarations."""
    caplog.set_level(logging.INFO)

    # 1. Project does NOT declare technology, but task metadata has language="typescript"
    caplog.clear()
    detected_none = detect_task_stack("typescript", project_tech=None)
    assert detected_none == frozenset({"typescript"})
    assert "Stack detected from metadata: typescript" in caplog.text

    # 2. Project declares ONLY python backend, but task metadata has language="typescript"
    caplog.clear()
    detected_py = detect_task_stack("typescript", project_tech={"backend": ["python"]})
    assert detected_py == frozenset({"typescript"})
    assert "Stack detected from metadata: typescript" in caplog.text


def test_spec_template_headings_present_in_all_fixtures():
    """Verifies Spec prompt contains all 7 template headings for every fixture."""
    from asf.agents.loading import load_spec_prompts, load_spec_template

    prompts = load_spec_prompts()
    template = load_spec_template(Path("templates"))
    assert len(template.required_sections) == 7

    fixtures = [
        "Create Python word count utility in word_count.py",
        "Create CreateBiddingForm.tsx with React form validation",
        "Fullstack feature with FastAPI auctions.py and React CreateBiddingForm.tsx",
    ]
    proj_ctx = {
        "skills": [{"id": "security", "digest": "Specify explicit security requirements."}],
        "reviewRules": "<!-- stack: typescript -->\n## 1. General\nclean code",
        "technology": {"frontend": ["react", "typescript"], "backend": ["python"]},
    }

    for req in fixtures:
        ctx = SpecPromptContext(
            prompts=prompts,
            template=template,
            requirement=req,
            language=None,
            project_context=proj_ctx,
        )
        msgs = build_spec_messages(ctx)
        user_content = msgs[1].content
        for heading in template.required_sections:
            assert heading in user_content, f"Missing heading {heading} in fixture: {req}"


def test_skill_missing_digest_logs_warning_and_omits(caplog):
    """Design agents omit skills without a digest field and log a WARNING."""
    caplog.set_level(logging.WARNING)
    project = {
        "skills": [
            {"id": "general", "content": "General body only, no digest"},
            {"id": "security", "digest": "Explicit security rules.", "content": "Body"},
        ],
    }
    selected = skills_for_agent(project, "spec")
    assert selected == [("security", "Explicit security rules.")]
    assert "Skill 'general' has no digest; omitting from design agent 'spec'" in caplog.text


def test_signal_detection_file_extensions_and_dotnet():
    """File extensions in text_signal (e.g. calc.py, Foo.tsx) and ASP.NET are detected."""
    assert detect_task_stack(None, {"backend": ["python"]}, "Update calc.py") == frozenset(
        {"python"}
    )
    assert detect_task_stack(None, {"frontend": ["typescript"]}, "Create Foo.tsx") == frozenset(
        {"typescript"}
    )
    assert detect_task_stack(
        None, {"backend": ["csharp"]}, "Build an ASP.NET Core API"
    ) == frozenset({"csharp"})
    assert detect_task_stack(
        None, {"frontend": ["typescript"]}, "Edit src/app/main.ts"
    ) == frozenset({"typescript"})
    tech_all = {"backend": ["python", "java"], "frontend": ["typescript"]}
    assert detect_task_stack(None, tech_all, "Handle reaction results") == frozenset()
    assert detect_task_stack(None, {"backend": ["java"]}, "Spring cleaning task") == frozenset()


def test_section_classification_fixes():
    """Heading-first classification avoids false body matches and covers security/api/tests."""
    assert (
        classify_section_scope(
            "## 4. Tests and Review",
            "## 4. Tests and Review\n\nCover authorization, validation.",
        )
        == "test-style"
    )
    assert (
        classify_section_scope(
            "## 1. Readability and Structure",
            "## 1. Readability and Structure\n\nUse clear naming.",
        )
        == "structure"
    )
    assert (
        classify_section_scope(
            "## 4. Async and Error Handling",
            "## 4. Async and Error Handling\n\nNever block in request or library code.",
        )
        == "coding-detail"
    )
    assert (
        classify_section_scope(
            "## 3. SQL / Injection Protection",
            "## 3. SQL / Injection Protection\n\nUse parameterized queries.",
        )
        == "security"
    )
    assert (
        classify_section_scope(
            "## 7. Error Message Disclosure",
            "## 7. Error Message Disclosure\n\nDo NOT expose internal stack traces.",
        )
        == "security"
    )
    assert (
        classify_section_scope(
            "## 4. Errors and HTTP Status",
            "## 4. Errors and HTTP Status\n\nUse ProblemDetails.",
        )
        == "api"
    )


def test_document_stack_ignores_body_tokens_like_ts_in_inputs():
    """_document_stack only inspects the # title line, not body text like 'inputs'."""
    doc = "# General Rules\nAlways validate inputs at API boundaries."
    assert _document_stack(doc) is None


def test_spec_f2_system_prompt_piece_sum_equals_total():
    """Verifies sum of exact prompt pieces equals len(system) for F2 TS/React Spec."""
    from asf.agents._shared.rules import RulesFilterOptions, rules_section
    from asf.agents._shared.skills import skills_section
    from asf.agents.loading import load_spec_prompts, load_spec_template
    from asf.agents.spec.prompts import _RULES_INTRO

    prompts = load_spec_prompts()
    template = load_spec_template(Path("templates"))
    ts_rules = Path("projects/rules/languages/typescript.md").read_text(encoding="utf-8")
    proj_ctx = {
        "name": "MyAgent",
        "technology": {"backend": ["python", "fastapi"], "frontend": ["react", "typescript"]},
        "reviewRules": ts_rules,
        "skills": [
            {"id": "general", "digest": "Keep changes minimal."},
            {"id": "security", "digest": "Specify security requirements."},
        ],
    }
    req = "Create CreateBiddingForm.tsx with React form validation"
    stack = detect_task_stack(None, proj_ctx["technology"], text_signal=req)
    assert stack == frozenset({"typescript"})

    system_msg = build_spec_messages(
        SpecPromptContext(
            prompts=prompts,
            template=template,
            requirement=req,
            language=None,
            project_context=proj_ctx,
        )
    )[0].content
    base = prompts.contract + prompts.system
    rules_piece = rules_section(
        proj_ctx,
        _RULES_INTRO,
        RulesFilterOptions(agent="spec", stack=stack),
    )
    skills_piece = skills_section(proj_ctx, "spec", stack=stack)
    assert len(base) + len(rules_piece) + len(skills_piece) == len(system_msg)
    assert base + rules_piece + skills_piece == system_msg


def _build_all_agent_systems(revision: bool = False) -> list[tuple[str, str]]:
    from asf.agents.loading import (
        load_plan_prompts,
        load_plan_template,
        load_spec_prompts,
        load_spec_template,
        load_task_prompts,
        load_task_template,
    )
    from asf.agents.plan.prompts import PlanPromptContext, build_plan_messages
    from asf.agents.task.prompts import TaskPromptContext, build_task_messages

    tdir = Path("templates")
    spec_art = {"id": "a1", "version": "1", "content": {"text": "# SPEC: t\n## Background / Goal"}}
    plan_art = {"id": "b1", "version": "1", "content": {"text": "# PLAN: t\n## Linked SPEC"}}
    prev_spec = ("1", "# SPEC: old") if revision else None
    prev_plan = ("1", "# PLAN: old") if revision else None
    prev_task = ("1", '{"tasks":[]}') if revision else None
    spec_sys = build_spec_messages(
        SpecPromptContext(
            load_spec_prompts(), load_spec_template(tdir), "req", None, None, prev_spec
        )
    )[0].content
    plan_sys = build_plan_messages(
        PlanPromptContext(
            load_plan_prompts(), load_plan_template(tdir), spec_art, None, None, prev_plan
        )
    )[0].content
    task_sys = build_task_messages(
        TaskPromptContext(
            load_task_prompts(),
            load_task_template(tdir),
            spec_art,
            plan_art,
            None,
            None,
            prev_task,
        )
    )[0].content
    return [("spec", spec_sys), ("plan", plan_sys), ("task", task_sys)]


def _extract_section_block(system: str, header: str) -> str:
    if header not in system:
        return ""
    after = system.split(header, 1)[1]
    for stop in ("\n\nYou are revising", "\n\nRevision instructions:", "\n\nProject "):
        if stop in after:
            after = after.split(stop, 1)[0]
    return after


def test_instruction_numbering_is_sequential_for_all_agents():
    """Instructions (and Revision instructions) for Spec, Plan, and Task must be sequential."""
    import re

    pattern = re.compile(r"^\d+\. ", re.MULTILINE)
    for revision in (False, True):
        for agent_name, system in _build_all_agent_systems(revision=revision):
            inst_block = _extract_section_block(system, "Instructions:\n")
            nums = [int(m.group().rstrip(". ")) for m in pattern.finditer(inst_block)]
            assert nums == list(range(1, len(nums) + 1)), (
                f"{agent_name} (rev={revision}) Instructions not sequential: {nums}"
            )
            if revision:
                rev_block = _extract_section_block(system, "Revision instructions:\n")
                rnums = [int(m.group().rstrip(". ")) for m in pattern.finditer(rev_block)]
                assert rnums == list(range(1, len(rnums) + 1)), (
                    f"{agent_name} Revision instructions not sequential: {rnums}"
                )


def test_generic_heading_with_api_body_is_omitted():
    """Headed sections with generic titles like '## Rules 1' are classified by heading only."""
    rules = (
        "<!-- stack: typescript -->\n"
        "# TypeScript Rules\n"
        "## Rules 1\n"
        "Always validate API request and response DTO contracts.\n"
    )
    scope = classify_section_scope(
        "## Rules 1",
        "## Rules 1\nAlways validate API request and response DTO contracts.",
    )
    assert scope == "coding-detail"
    filtered = filter_rules_for_task(
        rules,
        "spec",
        frozenset({"typescript"}),
    )
    assert filtered == ""


def test_classify_section_scope_word_boundaries():
    """Keyword matching uses word boundaries for both positive plurals and negative substrings."""
    negative_cases = [
        ("## Capitalization", "Use PascalCase."),
        ("## Authoring guide", "Write clear docs."),
        ("## Classification rules", "Group items cleanly."),
        ("## Enumerating options", "List all choices."),
    ]
    for heading, body in negative_cases:
        assert classify_section_scope(heading, f"{heading}\n{body}") == "coding-detail"

    positive_cases = [
        ("## Authentication", "security"),
        ("## Authorize", "security"),
        ("## Permissions", "security"),
        ("## Credentials", "security"),
        ("## APIs", "api"),
        ("## Endpoints", "api"),
        ("## DTOs", "api"),
        ("## Enums", "naming"),
        ("## Constants", "naming"),
    ]
    for heading, expected in positive_cases:
        assert classify_section_scope(heading, f"{heading}\nBody text.") == expected


def test_plan_java_vhpc_receives_java_spring_digests_and_react_does_not():
    """Plan prompt for Java vhpc task includes java/spring digests; React-only task omits them."""
    from asf.agents.loading import load_plan_prompts, load_plan_template
    from asf.agents.plan.prompts import PlanPromptContext, build_plan_messages
    from asf.api.demo import DemoFactoryService
    from asf.configuration.loader import load_projects

    demo = DemoFactoryService.__new__(DemoFactoryService)
    demo._projects_dir = Path("projects")
    demo._skills_dir = Path("skills")
    profile = load_projects(demo._projects_dir)["vhpc"].to_contract()
    demo._project_profiles = {"vhpc": profile}
    real_skills = demo._project_skills("vhpc")
    proj_ctx = {"name": "vhpc", "technology": profile.get("technology", {}), "skills": real_skills}

    java_spec = {
        "id": "s1",
        "version": "1",
        "content": {"text": "# SPEC: Alloc\nImplement Spring Boot Java 21 controller."},
    }
    java_plan = build_plan_messages(
        PlanPromptContext(
            load_plan_prompts(), load_plan_template(Path("templates")), java_spec, None, proj_ctx
        )
    )[0].content
    assert "### Skill: java" in java_plan
    assert "### Skill: spring" in java_plan
    assert "### Skill: react" not in java_plan

    react_spec = {
        "id": "s2",
        "version": "1",
        "content": {"text": "# SPEC: Form\nCreate AllocationForm.tsx in React TypeScript."},
    }
    react_plan = build_plan_messages(
        PlanPromptContext(
            load_plan_prompts(), load_plan_template(Path("templates")), react_spec, None, proj_ctx
        )
    )[0].content
    assert "### Skill: java" not in react_plan
    assert "### Skill: spring" not in react_plan
    assert "### Skill: react" in react_plan
