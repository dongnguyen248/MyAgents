"""Prompt section builders shared by the text agents' prompts."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from asf.contracts.models import ApprovalFeedback

PROJECT_CONTEXT_KEYS = ("name", "description", "technology")


def _filter_technology(
    technology: Any,
    task_stack: frozenset[str] | None,
) -> dict[str, list[str]] | None:
    if not isinstance(technology, dict) or not task_stack:
        return None
    from asf.agents._shared.rules import _canonical_stack

    filtered: dict[str, list[str]] = {}
    for group, items in technology.items():
        if isinstance(items, list):
            matching = [str(item) for item in items if _canonical_stack(str(item)) in task_stack]
            if matching:
                filtered[str(group)] = matching
    return filtered or None


def project_context_section(
    project_context: dict[str, Any] | None,
    task_stack: frozenset[str] | None = None,
) -> str:
    if not project_context:
        return ""
    whitelisted: dict[str, Any] = {}
    for key in ("name", "description"):
        if key in project_context:
            whitelisted[key] = project_context[key]
    if "technology" in project_context:
        filtered_tech = _filter_technology(project_context["technology"], task_stack)
        if filtered_tech:
            whitelisted["technology"] = filtered_tech
    if not whitelisted:
        return ""
    proj_str = json.dumps(whitelisted, indent=2)
    return f"## Project context\n{proj_str}"


def revision_sections(
    previous: tuple[str, str] | None,
    heading: str,
    feedback: Sequence[ApprovalFeedback],
) -> list[str]:
    if previous is None:
        return []
    prev_version, prev_text = previous
    sections = [f"## {heading} (version {prev_version})\n{prev_text}"]
    feedback_lines = [f"- [{fb.decision}] {fb.reviewer}: {fb.comment}" for fb in feedback]
    feedback_str = "\n".join(feedback_lines) if feedback_lines else "none"
    sections.append(f"## Reviewer feedback\n{feedback_str}")
    return sections


def linked_artifact_section(artifact: dict[str, Any], heading: str) -> str:
    artifact_id = artifact.get("id", "unknown")
    version = artifact.get("version", "unknown")
    content = artifact.get("content")
    if isinstance(content, dict):
        text = content.get("text", "")
    elif isinstance(content, str):
        text = content
    else:
        text = ""
    return f"## {heading}\nID: {artifact_id}\nVersion: {version}\n\n{text}"
