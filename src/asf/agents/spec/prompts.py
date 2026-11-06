from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from asf.agents._shared.rules import rules_section
from asf.agents._shared.skills import skills_section
from asf.contracts.models import ApprovalFeedback, ModelMessage

__all__ = [
    "SpecPromptContext",
    "SpecPrompts",
    "SpecTemplate",
    "build_spec_messages",
    "build_user_message",
]

_PROJECT_CONTEXT_KEYS = ("name", "description", "technology")

_RULES_INTRO = (
    "Project standards — where these standards govern what the"
    " specification describes (API contracts, security requirements,"
    " naming and structure), write the specification to comply with"
    " them; where they conflict with the output contract above, the"
    " output contract wins:"
)


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


@dataclass(frozen=True)
class SpecPromptContext:
    prompts: SpecPrompts
    template: SpecTemplate
    requirement: str
    language: str | None
    project_context: dict[str, Any] | None
    previous_spec: tuple[str, str] | None = None
    feedback: Sequence[ApprovalFeedback] = ()


def _project_context_section(context: SpecPromptContext) -> str:
    project = context.project_context
    if not project:
        return "## Project context\nnone"
    whitelisted = {key: project[key] for key in _PROJECT_CONTEXT_KEYS if key in project}
    proj_str = json.dumps(whitelisted, indent=2) if whitelisted else "none"
    return f"## Project context\n{proj_str}"


def _revision_sections(context: SpecPromptContext) -> list[str]:
    if context.previous_spec is None:
        return []
    prev_version, prev_text = context.previous_spec
    sections = [f"## Previous specification (version {prev_version})\n{prev_text}"]
    feedback_lines = [f"- [{fb.decision}] {fb.reviewer}: {fb.comment}" for fb in context.feedback]
    feedback_str = "\n".join(feedback_lines) if feedback_lines else "none"
    sections.append(f"## Reviewer feedback\n{feedback_str}")
    return sections


def build_user_message(context: SpecPromptContext) -> str:
    """Builds the user prompt message with fixed sections."""
    language = context.language
    lang_str = language if language else "same language as the requirement"
    sections = [
        f"## Requirement\n{context.requirement}",
        f"## Output language\n{lang_str}",
        _project_context_section(context),
        f"## Template\n{context.template.text}",
        *_revision_sections(context),
    ]
    return "\n\n".join(sections)


def _system_content(context: SpecPromptContext) -> str:
    prompts = context.prompts
    if context.previous_spec is not None:
        content = f"{prompts.system}\n\n{prompts.revision}"
    else:
        content = prompts.system
    content += rules_section(context.project_context, _RULES_INTRO)
    content += skills_section(context.project_context, "spec")
    return content


def build_spec_messages(context: SpecPromptContext) -> list[ModelMessage]:
    """Constructs the system and user messages for SpecAgent."""
    return [
        ModelMessage(role="system", content=_system_content(context)),
        ModelMessage(role="user", content=build_user_message(context)),
    ]
