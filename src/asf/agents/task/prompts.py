from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from asf.agents._shared.rules import rules_section
from asf.agents._shared.skills import skills_section
from asf.agents.plan.milestones import (
    MAX_MILESTONES,
    milestone_ancestors,
    parse_milestones,
)
from asf.contracts.models import ApprovalFeedback, ModelMessage

__all__ = [
    "TaskPrompts",
    "TaskTemplate",
    "build_task_messages",
    "build_user_message",
    "validate_task_output",
    "parse_milestones",
    "milestone_ancestors",
    "MAX_MILESTONES",
]


@dataclass(frozen=True)
class TaskPrompts:
    system: str
    revision: str


@dataclass(frozen=True)
class TaskTemplate:
    text: str

    @classmethod
    def from_text(cls, text: str) -> TaskTemplate:
        return cls(text=text)


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


def build_user_message(
    spec_artifact: dict[str, Any],
    plan_artifact: dict[str, Any],
    language: str | None,
    project_context: dict[str, Any] | None,
    template_text: str,
    previous_task: tuple[str, str] | None = None,
    feedback: Sequence[ApprovalFeedback] = (),
) -> str:
    """Builds the user prompt message with fixed sections."""
    sections: list[str] = []

    # 1. Linked SPEC (input artifact)
    spec_id = spec_artifact.get("id", "unknown")
    spec_version = spec_artifact.get("version", "unknown")
    spec_text = ""
    if isinstance(spec_artifact.get("content"), dict):
        spec_text = spec_artifact["content"].get("text", "")
    elif isinstance(spec_artifact.get("content"), str):
        spec_text = spec_artifact["content"]

    sections.append(f"## Linked SPEC\nID: {spec_id}\nVersion: {spec_version}\n\n{spec_text}")

    # 2. Linked PLAN (input artifact)
    plan_id = plan_artifact.get("id", "unknown")
    plan_version = plan_artifact.get("version", "unknown")
    plan_text = ""
    if isinstance(plan_artifact.get("content"), dict):
        plan_text = plan_artifact["content"].get("text", "")
    elif isinstance(plan_artifact.get("content"), str):
        plan_text = plan_artifact["content"]

    sections.append(f"## Linked PLAN\nID: {plan_id}\nVersion: {plan_version}\n\n{plan_text}")

    # 3. Output language
    lang_str = language if language else "same language as the SPEC"
    sections.append(f"## Output language\n{lang_str}")

    # 4. Project context (whitelisted: name, description, technology)
    if project_context:
        whitelisted = {
            k: project_context[k]
            for k in ("name", "description", "technology")
            if k in project_context
        }
        proj_str = json.dumps(whitelisted, indent=2) if whitelisted else "none"
    else:
        proj_str = "none"
    sections.append(f"## Project context\n{proj_str}")

    # 5. Template
    sections.append(f"## Template\n{template_text}")

    # 6 & 7. Revision mode sections
    if previous_task is not None:
        prev_version, prev_text = previous_task
        sections.append(f"## Previous task (version {prev_version})\n{prev_text}")

        feedback_lines = [f"- [{fb.decision}] {fb.reviewer}: {fb.comment}" for fb in feedback]
        feedback_str = "\n".join(feedback_lines) if feedback_lines else "none"
        sections.append(f"## Reviewer feedback\n{feedback_str}")

    return "\n\n".join(sections)


def build_task_messages(
    prompts: TaskPrompts,
    template: TaskTemplate,
    spec_artifact: dict[str, Any],
    plan_artifact: dict[str, Any],
    language: str | None,
    project_context: dict[str, Any] | None,
    previous_task: tuple[str, str] | None = None,
    feedback: Sequence[ApprovalFeedback] = (),
) -> list[ModelMessage]:
    """Constructs the system and user messages for TaskAgent."""
    is_revision = previous_task is not None
    system_content = f"{prompts.system}\n\n{prompts.revision}" if is_revision else prompts.system
    system_content += rules_section(
        project_context,
        "Project development rules — the standards this project's code"
        " must follow. Break the work into tasks that comply with them,"
        " including any tasks the standards require (for example"
        " dedicated constants files, DTOs, or tests); where they"
        " conflict with the output contract above, the output contract"
        " wins:",
    )
    system_content += skills_section(project_context, "task")

    user_content = build_user_message(
        spec_artifact=spec_artifact,
        plan_artifact=plan_artifact,
        language=language,
        project_context=project_context,
        template_text=template.text,
        previous_task=previous_task,
        feedback=feedback,
    )

    return [
        ModelMessage(role="system", content=system_content),
        ModelMessage(role="user", content=user_content),
    ]
