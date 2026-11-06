"""Prompt section builders shared by the text agents' prompts."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from asf.contracts.models import ApprovalFeedback

PROJECT_CONTEXT_KEYS = ("name", "description", "technology")


def project_context_section(project_context: dict[str, Any] | None) -> str:
    if not project_context:
        return "## Project context\nnone"
    whitelisted = {
        key: project_context[key] for key in PROJECT_CONTEXT_KEYS if key in project_context
    }
    proj_str = json.dumps(whitelisted, indent=2) if whitelisted else "none"
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
