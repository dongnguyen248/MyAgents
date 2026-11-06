from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from asf.agents._shared.harness import (
    HarnessComponents,
    agent_skills_section,
    assemble_base_prompt,
    components_from_prompts,
    guardrails_memory_section,
)
from asf.agents._shared.prompt_context import (
    linked_artifact_section,
    project_context_section,
    revision_sections,
)
from asf.agents._shared.rules import rules_section
from asf.agents._shared.skills import skills_section
from asf.agents.plan.milestones import (
    MAX_MILESTONES,
    milestone_ancestors,
    parse_milestones,
)
from asf.contracts.models import ApprovalFeedback, ModelMessage

__all__ = [
    "TaskPromptContext",
    "TaskPrompts",
    "TaskTemplate",
    "build_task_messages",
    "build_user_message",
    "validate_task_output",
    "parse_milestones",
    "milestone_ancestors",
    "MAX_MILESTONES",
]

_RULES_INTRO = (
    "Project development rules — the standards this project's code"
    " must follow. Break the work into tasks that comply with them,"
    " including any tasks the standards require (for example"
    " dedicated constants files, DTOs, or tests); where they"
    " conflict with the output contract above, the output contract"
    " wins:"
)


@dataclass(frozen=True)
class TaskPrompts:
    system: str
    revision: str
    contract: str = ""


@dataclass(frozen=True)
class TaskTemplate:
    text: str

    @classmethod
    def from_text(cls, text: str) -> TaskTemplate:
        return cls(text=text)


@dataclass(frozen=True)
class TaskPromptContext:
    prompts: TaskPrompts
    template: TaskTemplate
    spec_artifact: dict[str, Any]
    plan_artifact: dict[str, Any]
    language: str | None
    project_context: dict[str, Any] | None
    previous_task: tuple[str, str] | None = None
    feedback: Sequence[ApprovalFeedback] = ()
    harness: HarnessComponents | None = None


def validate_task_output(task_text: str) -> list[str]:
    """Validates task JSON output structure.

    Returns a list of issue strings (empty if valid).
    """
    issues: list[str] = []

    try:
        data = json.loads(task_text)
    except json.JSONDecodeError as e:
        issues.append(f"Invalid JSON: {e}")
        return issues

    if not isinstance(data, dict):
        issues.append("Task output must be a JSON object")
        return issues

    if "tasks" not in data:
        issues.append("Missing 'tasks' key in JSON envelope")
        return issues

    tasks = data["tasks"]
    if not isinstance(tasks, list):
        issues.append("'tasks' must be a list")
        return issues

    return issues


def build_user_message(context: TaskPromptContext) -> str:
    """Builds the user prompt message with fixed sections."""
    language = context.language
    lang_str = language if language else "same language as the SPEC"
    sections = [
        linked_artifact_section(context.spec_artifact, "Linked SPEC"),
        linked_artifact_section(context.plan_artifact, "Linked PLAN"),
        f"## Output language\n{lang_str}",
        project_context_section(context.project_context),
        f"## Template\n{context.template.text}",
        *revision_sections(context.previous_task, "Previous task", context.feedback),
    ]
    return "\n\n".join(sections)


def _components(context: TaskPromptContext) -> HarnessComponents:
    if context.harness is not None:
        return context.harness
    prompts = context.prompts
    return components_from_prompts(
        contract=prompts.contract,
        system=prompts.system,
        revision=prompts.revision,
    )


def _system_content(context: TaskPromptContext) -> str:
    components = _components(context)
    content = assemble_base_prompt(components, revision=context.previous_task is not None)
    content += rules_section(context.project_context, _RULES_INTRO)
    content += guardrails_memory_section(components)
    content += skills_section(context.project_context, "task")
    content += agent_skills_section(components)
    return content


def build_task_messages(context: TaskPromptContext) -> list[ModelMessage]:
    """Constructs the system and user messages for TaskAgent."""
    return [
        ModelMessage(role="system", content=_system_content(context)),
        ModelMessage(role="user", content=build_user_message(context)),
    ]
