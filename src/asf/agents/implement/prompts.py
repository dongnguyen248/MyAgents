from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from asf.contracts.models import ModelMessage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImplementPrompts:
    """System prompt for ImplementAgent."""

    system: str


def build_implement_messages(
    *,
    prompts: ImplementPrompts,
    spec_artifact: dict[str, Any],
    plan_artifact: dict[str, Any],
    task_artifact: dict[str, Any],
    task_item_id: str,
    existing_files: dict[str, str],
    language: str | None,
    project_context: str | dict[str, Any] | None,
) -> list[ModelMessage]:
    """Build the message list for the ImplementAgent LLM call."""
    system_msg = prompts.system

    # Add enabled skills if present in project context
    skills_line = ""
    if project_context:
        if not isinstance(project_context, str):
            logger.warning("Project context is not JSON text; enabled skills omitted")
        else:
            try:
                proj = json.loads(project_context)
            except json.JSONDecodeError:
                logger.warning("Project context is invalid JSON; enabled skills omitted")
            else:
                if not isinstance(proj, dict):
                    logger.warning("Project context is not an object; enabled skills omitted")
                else:
                    skills = proj.get("enabledSkills", [])
                    if skills:
                        try:
                            skills_line = f"\nEnabled skills: {', '.join(skills)}"
                        except TypeError:
                            logger.warning(
                                "Project context has invalid enabled skills; enabled skills omitted"
                            )

    if skills_line:
        system_msg += skills_line

    # Build context sections
    sections: list[str] = []

    # SPEC content
    spec_text = ""
    if isinstance(spec_artifact, dict) and isinstance(spec_artifact.get("content"), dict):
        spec_text = spec_artifact["content"].get("text", "")
    if spec_text:
        sections.append("<<<SPEC>>>\n" + spec_text + "\n<<<END SPEC>>>")

    # PLAN content
    plan_text = ""
    if isinstance(plan_artifact, dict) and isinstance(plan_artifact.get("content"), dict):
        plan_text = plan_artifact["content"].get("text", "")
    if plan_text:
        sections.append("<<<PLAN>>>\n" + plan_text + "\n<<<END PLAN>>>")

    # TASK content - find the specific task item
    task_text = ""
    if isinstance(task_artifact, dict) and isinstance(task_artifact.get("content"), dict):
        content = task_artifact["content"]
        # Tasks may be in content["tasks"] directly or in content["text"] as JSON string
        tasks = None
        if isinstance(content.get("tasks"), list):
            tasks = content["tasks"]
        elif isinstance(content.get("text"), str):
            try:
                parsed = json.loads(content["text"])
                if isinstance(parsed.get("tasks"), list):
                    tasks = parsed["tasks"]
            except json.JSONDecodeError:
                pass
        if tasks:
            for task in tasks:
                if task.get("id") == task_item_id:
                    task_text = (
                        f"ID: {task.get('id')}\n"
                        f"Title: {task.get('title')}\n"
                        f"Description: {task.get('description')}\n"
                        f"Acceptance Criteria:\n"
                        + "\n".join(f"- {ac}" for ac in task.get("acceptanceCriteria", []))
                    )
                    if task.get("expectedFiles"):
                        task_text += "\nExpected Files:\n" + "\n".join(
                            f"- {f}" for f in task.get("expectedFiles", [])
                        )
                    task_text += f"\nVerification Hint: {task.get('verificationHint', '')}"
                    break
    if task_text:
        sections.append("<<<TASK ITEM>>>\n" + task_text + "\n<<<END TASK ITEM>>>")

    # Existing files
    if existing_files:
        file_sections = []
        for path, content in sorted(existing_files.items()):
            file_sections.append(f"<<<FILE: {path}>>>\n{content}\n<<<END FILE: {path}>>>")
        sections.append("\n".join(file_sections))

    context_block = "\n\n".join(sections)

    user_msg = (
        f"Implement the task item {task_item_id} based on the SPEC, "
        f"PLAN, and TASK ITEM above.\n\n{context_block}\n\n"
        "Return a JSON object with the following schema:\n"
        "{\n"
        '  "changes": [\n'
        '    {\n'
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

    return [
        ModelMessage(role="system", content=system_msg),
        ModelMessage(role="user", content=user_msg),
    ]


def render_code_markdown(
    changes: list[dict[str, Any]],
    spec_id: str,
    spec_version: str,
    plan_id: str,
    plan_version: str,
    task_item_id: str,
) -> str:
    """Deterministically render markdown from validated changes."""
    lines: list[str] = []
    lines.append("# CODE: Implementation")
    lines.append("")
    lines.append("## Linked Artifacts")
    lines.append(f"SPEC ID: {spec_id}")
    lines.append(f"SPEC Version: {spec_version}")
    lines.append(f"PLAN ID: {plan_id}")
    lines.append(f"PLAN Version: {plan_version}")
    lines.append(f"Task Item ID: {task_item_id}")
    lines.append("")

    for fc in changes:
        path = fc["path"]
        operation = fc["operation"]
        content = fc.get("content", "")
        lines.append(f"## File: {path}")
        lines.append(f"**Operation:** {operation}")
        lines.append("")
        if content:
            # Determine language from extension
            ext = path.split(".")[-1] if "." in path else ""
            lang_map = {
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
            lang = lang_map.get(ext, "")
            if lang:
                lines.append(f"```{lang}")
            else:
                lines.append("```")
            lines.append(content.rstrip())
            lines.append("```")
        lines.append("")

    return "\n".join(lines).strip()