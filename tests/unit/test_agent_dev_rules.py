"""Standing project rules reach every producing agent's system prompt.

The assembly resolves a project's standards into the run context as
``context["project"]["reviewRules"]``; Spec, Plan, Task, Implement, and
Fix must all develop against them (the Review Agent's criteria use is
covered in test_review_agent.py).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from asf.agents._shared.codegen import FixContext
from asf.agents._shared.rules import project_rules, rules_section
from asf.agents.fix.prompts import FixPrompts, build_fix_messages
from asf.agents.implement.prompts import (
    ImplementPromptContext,
    ImplementPrompts,
    build_implement_messages,
)
from asf.agents.plan.prompts import (
    PlanPromptContext,
    PlanPrompts,
    PlanTemplate,
    build_plan_messages,
)
from asf.agents.spec.prompts import (
    SpecPromptContext,
    SpecPrompts,
    SpecTemplate,
    build_spec_messages,
)
from asf.agents.task.prompts import (
    TaskPromptContext,
    TaskPrompts,
    TaskTemplate,
    build_task_messages,
)
from asf.contracts.models import AgentRequest

RULES = "Never hardcode an HTTP status code."
PROJECT = {"reviewRules": RULES}


@pytest.mark.parametrize(
    "project",
    [
        PROJECT,
        json.dumps(PROJECT),
        {"reviewRules": f"  {RULES}  "},
    ],
)
def test_project_rules_extracts_from_mapping_or_json(project: Any) -> None:
    assert project_rules(project) == RULES


@pytest.mark.parametrize(
    "project",
    [
        None,
        [],
        42,
        "{bad json",
        "[]",
        {},
        {"reviewRules": ""},
        {"reviewRules": "   "},
        {"reviewRules": 42},
        {"reviewRules": ["x"]},
    ],
)
def test_project_rules_rejects_absent_or_invalid_values(project: Any) -> None:
    assert project_rules(project) == ""
    assert rules_section(project, "Intro:") == ""


def test_implement_messages_carry_the_rules() -> None:
    messages = build_implement_messages(
        ImplementPromptContext(
            prompts=ImplementPrompts(system="system"),
            spec_artifact={},
            plan_artifact={},
            task_artifact={},
            task_item_id="T1",
            existing_files={},
            language=None,
            project_context=PROJECT,
        )
    )
    assert "Project development rules" in messages[0].content
    assert RULES in messages[0].content


def test_fix_messages_carry_the_rules() -> None:
    request = AgentRequest(
        request_id="r1",
        task_id="t1",
        project_id="p1",
        workflow_id="w1",
        agent_id="agent-fix",
        input={"ref": "main"},
        context={"project": PROJECT},
    )
    context = FixContext(
        task_id="T1",
        spec_summary="",
        plan_summary="",
        task_summary="",
        expected_files=(),
        existing_files={},
        review_findings=(),
        previous_changeset=None,
    )
    messages = build_fix_messages(FixPrompts(system="system"), request, context)
    assert "Project development rules" in messages[0].content
    assert RULES in messages[0].content


def test_spec_messages_carry_the_rules() -> None:
    messages = build_spec_messages(
        SpecPromptContext(
            prompts=SpecPrompts(system="system", revision="revision"),
            template=SpecTemplate.from_text("template"),
            requirement="Build a thing",
            language=None,
            project_context=PROJECT,
        )
    )
    assert "Project standards" in messages[0].content
    assert RULES in messages[0].content


def test_plan_messages_carry_the_rules() -> None:
    messages = build_plan_messages(
        PlanPromptContext(
            prompts=PlanPrompts(system="system", revision="revision"),
            template=PlanTemplate.from_text("template"),
            spec_artifact={},
            language=None,
            project_context=PROJECT,
        )
    )
    assert "Project development rules" in messages[0].content
    assert RULES in messages[0].content


def test_task_messages_carry_the_rules() -> None:
    messages = build_task_messages(
        TaskPromptContext(
            prompts=TaskPrompts(system="system", revision="revision"),
            template=TaskTemplate.from_text("template"),
            spec_artifact={},
            plan_artifact={},
            language=None,
            project_context=PROJECT,
        )
    )
    assert "Project development rules" in messages[0].content
    assert RULES in messages[0].content


@pytest.mark.parametrize("project_context", [None, {}, {"reviewRules": ""}])
def test_agents_without_rules_keep_their_plain_system_prompt(
    project_context: Any,
) -> None:
    messages = build_plan_messages(
        PlanPromptContext(
            prompts=PlanPrompts(system="system", revision="revision"),
            template=PlanTemplate.from_text("template"),
            spec_artifact={},
            language=None,
            project_context=project_context,
        )
    )
    assert messages[0].content == "system"
