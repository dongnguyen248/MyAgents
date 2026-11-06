from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from asf.agents._shared.code_agents import task_items_from_content
from asf.agents._shared.context_slicing import slice_plan, slice_spec
from asf.agents._shared.harness import (
    HarnessComponents,
    agent_skills_section,
    assemble_base_prompt,
    guardrails_memory_section,
)
from asf.agents._shared.rules import rules_section
from asf.agents._shared.skills import skills_section
from asf.contracts.models import ModelMessage
from asf.tools.edit_blocks import BLOCKS_FORMAT_INSTRUCTIONS

logger = logging.getLogger(__name__)

_RULES_INTRO = (
    "Project development rules — the standards this project's code"
    " must follow. Write code that complies with them; where they"
    " conflict with the output contract above, the output contract"
    " wins:"
)

_JSON_FORMAT_BLOCK = (
    "Return a JSON object with the following schema:\n"
    "{\n"
    '  "changes": [\n'
    "    {\n"
    '      "path": "string (relative POSIX path, no leading /)",\n'
    '      "operation": "create|modify|delete",\n'
    '      "content": "string (required for create/modify, omitted for delete)"\n'
    "    }\n"
    "  ]\n"
    "}\n\n"
    "Rules:\n"
    "- Full file contents only\n"
    "- No diffs\n"
    "- Paths must be from the task item's Expected Files list\n"
    "- For modify/delete: the file must exist at the given ref\n"
    "- For create: the file must not exist at the given ref\n"
    "- No NUL bytes, valid UTF-8 only\n"
    "- No secrets in generated content\n"
    "- Empty change set is not allowed\n"
    "- Output valid JSON only, no extra text"
)

_LANGUAGE_BY_EXTENSION = {
    "py": "python",
    "js": "javascript",
    "ts": "typescript",
    "java": "java",
    "go": "go",
    "rs": "rust",
    "cpp": "cpp",
    "c": "c",
    "cs": "csharp",
    "rb": "ruby",
    "php": "php",
    "swift": "swift",
    "kt": "kotlin",
    "scala": "scala",
    "sh": "bash",
    "yaml": "yaml",
    "yml": "yaml",
    "json": "json",
    "md": "markdown",
    "txt": "text",
}


@dataclass(frozen=True)
class ImplementPrompts:
    """System prompt for ImplementAgent."""

    system: str
    contract: str = ""
    tool_guidance: str = ""
    guardrails: str = ""
    memory: str = ""
    skills: Mapping[str, str] = field(default_factory=dict)

    def to_components(self) -> HarnessComponents:
        """The harness these loaded prompt files represent on their own."""
        return HarnessComponents(
            contract=self.contract,
            system=self.system,
            guardrails=self.guardrails,
            memory=self.memory,
            tool_guidance=self.tool_guidance,
            skills=self.skills,
        )


@dataclass(frozen=True)
class ImplementPromptContext:
    prompts: ImplementPrompts
    spec_artifact: dict[str, Any]
    plan_artifact: dict[str, Any]
    task_artifact: dict[str, Any]
    task_item_id: str
    existing_files: dict[str, str]
    language: str | None
    project_context: str | dict[str, Any] | None
    edit_format: str = "blocks"
    repo_map: str = ""
    harness: HarnessComponents | None = None


@dataclass(frozen=True)
class CodeMarkdownContext:
    changes: list[dict[str, Any]]
    spec_id: str
    spec_version: str
    plan_id: str
    plan_version: str
    task_item_id: str


def build_implement_messages(context: ImplementPromptContext) -> list[ModelMessage]:
    """Build the message list for the ImplementAgent LLM call."""
    task_item = _find_task_item(context.task_artifact, context.task_item_id)
    messages = [ModelMessage(role="system", content=_system_message(context))]
    stable_sections = _stable_sections(context, task_item)
    if stable_sections:
        messages.append(ModelMessage(role="user", content="\n\n".join(stable_sections)))
    messages.append(ModelMessage(role="user", content=_user_message(context, task_item)))
    return messages


def _components(context: ImplementPromptContext) -> HarnessComponents:
    if context.harness is not None:
        return context.harness
    return context.prompts.to_components()


def _system_message(context: ImplementPromptContext) -> str:
    components = _components(context)
    system_msg = assemble_base_prompt(components)
    skills_line = _enabled_skills_line(context.project_context)
    if skills_line:
        system_msg += skills_line
    system_msg += rules_section(context.project_context, _RULES_INTRO)
    system_msg += guardrails_memory_section(components)
    system_msg += skills_section(context.project_context, "implement")
    system_msg += agent_skills_section(components)
    return system_msg


def _enabled_skills_line(project_context: str | dict[str, Any] | None) -> str:
    project = _project_object(project_context)
    if project is None:
        return ""
    skills = project.get("enabledSkills", [])
    if not skills:
        return ""
    try:
        return f"\nEnabled skills: {', '.join(skills)}"
    except TypeError:
        logger.warning("Project context has invalid enabled skills; enabled skills omitted")
        return ""


def _project_object(project_context: str | dict[str, Any] | None) -> dict[str, Any] | None:
    if not project_context:
        return None
    if not isinstance(project_context, str):
        logger.warning("Project context is not JSON text; enabled skills omitted")
        return None
    try:
        project = json.loads(project_context)
    except json.JSONDecodeError:
        logger.warning("Project context is invalid JSON; enabled skills omitted")
        return None
    if not isinstance(project, dict):
        logger.warning("Project context is not an object; enabled skills omitted")
        return None
    return project


def _find_task_item(task_artifact: dict[str, Any], task_item_id: str) -> dict[str, Any] | None:
    if not (isinstance(task_artifact, dict) and isinstance(task_artifact.get("content"), dict)):
        return None
    try:
        candidates = task_items_from_content(task_artifact["content"])
    except (ValueError, TypeError):
        candidates = []
    return next((task for task in candidates if task.get("id") == task_item_id), None)


def _artifact_text(artifact: dict[str, Any]) -> Any:
    if isinstance(artifact, dict) and isinstance(artifact.get("content"), dict):
        return artifact["content"].get("text", "")
    return ""


def _stable_sections(
    context: ImplementPromptContext, task_item: dict[str, Any] | None
) -> list[str]:
    sections: list[str] = []
    spec_text = _artifact_text(context.spec_artifact)
    if spec_text:
        sliced = slice_spec(
            spec_text,
            task_title=_task_field(task_item, "title"),
            task_description=_task_field(task_item, "description"),
        )
        sections.append("<<<SPEC>>>\n" + sliced + "\n<<<END SPEC>>>")
    plan_text = _artifact_text(context.plan_artifact)
    if plan_text:
        sections.append("<<<PLAN>>>\n" + _sliced_plan(plan_text, task_item) + "\n<<<END PLAN>>>")
    return sections


def _task_field(task_item: dict[str, Any] | None, name: str) -> str:
    if task_item is None:
        return ""
    return str(task_item.get(name, ""))


def _sliced_plan(plan_text: str, task_item: dict[str, Any] | None) -> str:
    milestone_ref = None
    if task_item and task_item.get("milestoneRef"):
        milestone_ref = str(task_item["milestoneRef"])
    return slice_plan(plan_text, milestone_ref)


def _user_message(context: ImplementPromptContext, task_item: dict[str, Any] | None) -> str:
    context_block = "\n\n".join(_changing_sections(context, task_item))
    format_block = _format_block(context.edit_format, _components(context).tool_guidance)
    return (
        f"Implement the task item {context.task_item_id} based on the SPEC, "
        f"PLAN, and TASK ITEM.\n\n{context_block}\n\n"
        f"{format_block}"
    )


def _changing_sections(
    context: ImplementPromptContext, task_item: dict[str, Any] | None
) -> list[str]:
    sections: list[str] = []
    task_text = _task_item_text(task_item)
    if task_text:
        sections.append("<<<TASK ITEM>>>\n" + task_text + "\n<<<END TASK ITEM>>>")
    if context.existing_files:
        sections.append(_files_section(context.existing_files))
    if context.repo_map:
        sections.append("<<<REPO MAP>>>\n" + context.repo_map + "\n<<<END REPO MAP>>>")
    return sections


def _task_item_text(task_item: dict[str, Any] | None) -> str:
    if task_item is None:
        return ""
    text = (
        f"ID: {task_item.get('id')}\n"
        f"Title: {task_item.get('title')}\n"
        f"Description: {task_item.get('description')}\n"
        "Acceptance Criteria:\n"
        + "\n".join(f"- {ac}" for ac in task_item.get("acceptanceCriteria", []))
    )
    if task_item.get("expectedFiles"):
        text += "\nExpected Files:\n" + "\n".join(
            f"- {path}" for path in task_item.get("expectedFiles", [])
        )
    text += f"\nVerification Hint: {task_item.get('verificationHint', '')}"
    return text


def _files_section(existing_files: dict[str, str]) -> str:
    file_sections = []
    for path, content in sorted(existing_files.items()):
        file_sections.append(f"<<<FILE: {path}>>>\n{content}\n<<<END FILE: {path}>>>")
    return "\n".join(file_sections)


def _format_block(edit_format: str, tool_guidance: str) -> str:
    if edit_format == "blocks":
        return BLOCKS_FORMAT_INSTRUCTIONS + tool_guidance
    return _JSON_FORMAT_BLOCK


def render_code_markdown(context: CodeMarkdownContext) -> str:
    """Deterministically render markdown from validated changes."""
    lines = _header_lines(context)
    for change in context.changes:
        lines.extend(_change_lines(change))
    return "\n".join(lines).strip()


def _header_lines(context: CodeMarkdownContext) -> list[str]:
    return [
        "# CODE: Implementation",
        "",
        "## Linked Artifacts",
        f"SPEC ID: {context.spec_id}",
        f"SPEC Version: {context.spec_version}",
        f"PLAN ID: {context.plan_id}",
        f"PLAN Version: {context.plan_version}",
        f"Task Item ID: {context.task_item_id}",
        "",
    ]


def _change_lines(change: dict[str, Any]) -> list[str]:
    path = change["path"]
    lines = [f"## File: {path}", f"**Operation:** {change['operation']}", ""]
    content = change.get("content", "")
    if content:
        lines.append(f"```{_language_for(path)}")
        lines.append(content.rstrip())
        lines.append("```")
    lines.append("")
    return lines


def _language_for(path: str) -> str:
    extension = path.split(".")[-1] if "." in path else ""
    return _LANGUAGE_BY_EXTENSION.get(extension, "")
