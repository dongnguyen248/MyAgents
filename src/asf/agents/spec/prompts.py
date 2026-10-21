from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from asf.contracts.models import ApprovalFeedback, ModelMessage

__all__ = [
    "SpecPrompts",
    "SpecTemplate",
    "build_spec_messages",
    "build_user_message",
]


@dataclass(frozen=True)
class SpecPrompts:
    system: str
    revision: str


@dataclass(frozen=True)
class SpecTemplate:
    text: str
    required_sections: list[str]

    @classmethod
    def from_text(cls, text: str) -> SpecTemplate:
        sections: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("## "):
                sections.append(stripped)
        return cls(text=text, required_sections=sections)


def build_user_message(
    requirement: str,
    language: str | None,
    project_context: dict[str, Any] | None,
    template_text: str,
    previous_spec: tuple[str, str] | None = None,
    feedback: Sequence[ApprovalFeedback] = (),
) -> str:
    """Builds the user prompt message with fixed sections."""
    sections: list[str] = []

    # 1. Requirement
    sections.append(f"## Requirement\n{requirement}")

    # 2. Output language
    lang_str = language if language else "same language as the requirement"
    sections.append(f"## Output language\n{lang_str}")

    # 3. Project context (whitelisted: name, description, technology)
    if project_context:
        whitelisted = {
            k: project_context[k]
            for k in ("name", "description", "technology")
            if k in project_context
        }
        if whitelisted:
            proj_str = json.dumps(whitelisted, indent=2)
        else:
            proj_str = "none"
    else:
        proj_str = "none"
    sections.append(f"## Project context\n{proj_str}")

    # 4. Template
    sections.append(f"## Template\n{template_text}")

    # 5 & 6. Revision mode sections
    if previous_spec is not None:
        prev_version, prev_text = previous_spec
        sections.append(f"## Previous specification (version {prev_version})\n{prev_text}")

        feedback_lines = [
            f"- [{fb.decision}] {fb.reviewer}: {fb.comment}"
            for fb in feedback
        ]
        feedback_str = "\n".join(feedback_lines) if feedback_lines else "none"
        sections.append(f"## Reviewer feedback\n{feedback_str}")

    return "\n\n".join(sections)


def build_spec_messages(
    prompts: SpecPrompts,
    template: SpecTemplate,
    requirement: str,
    language: str | None,
    project_context: dict[str, Any] | None,
    previous_spec: tuple[str, str] | None = None,
    feedback: Sequence[ApprovalFeedback] = (),
) -> list[ModelMessage]:
    """Constructs the system and user messages for SpecAgent."""
    is_revision = previous_spec is not None
    if is_revision:
        system_content = f"{prompts.system}\n\n{prompts.revision}"
    else:
        system_content = prompts.system

    user_content = build_user_message(
        requirement=requirement,
        language=language,
        project_context=project_context,
        template_text=template.text,
        previous_spec=previous_spec,
        feedback=feedback,
    )

    return [
        ModelMessage(role="system", content=system_content),
        ModelMessage(role="user", content=user_content),
    ]
