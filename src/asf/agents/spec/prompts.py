from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from asf.agents._shared.design_prompts import (
    DesignSystemOptions,
    build_design_messages,
    build_design_system_content,
    build_design_user_content,
    format_language_section,
)
from asf.agents._shared.harness import (
    HarnessComponents,
)
from asf.agents._shared.prompt_context import project_context_section, revision_sections
from asf.agents._shared.rules import detect_task_stack
from asf.contracts.models import ApprovalFeedback, ModelMessage

__all__ = [
    "SpecPromptContext",
    "SpecPrompts",
    "SpecTemplate",
    "build_spec_messages",
    "build_user_message",
]

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
    contract: str = ""
    guardrails: str = ""
    memory: str = ""
    skills: Mapping[str, str] = field(default_factory=dict)

    def to_components(self) -> HarnessComponents:
        """The harness these loaded prompt files represent on their own."""
        return HarnessComponents(
            contract=self.contract,
            system=self.system,
            revision=self.revision,
            guardrails=self.guardrails,
            memory=self.memory,
            skills=self.skills,
        )


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
    harness: HarnessComponents | None = None


def build_user_message(context: SpecPromptContext) -> str:
    """Builds the user prompt message with fixed sections."""
    tech = (context.project_context or {}).get("technology")
    stack = detect_task_stack(context.language, tech, text_signal=context.requirement)
    sections = [
        f"## Requirement\n{context.requirement}",
        format_language_section(context.language),
        project_context_section(context.project_context, task_stack=stack),
        f"## Template\n{context.template.text}",
        *revision_sections(context.previous_spec, "Previous specification", context.feedback),
    ]
    return build_design_user_content(sections)


def _components(context: SpecPromptContext) -> HarnessComponents:
    if context.harness is not None:
        return context.harness
    return context.prompts.to_components()


def _system_content(context: SpecPromptContext) -> str:
    components = _components(context)
    tech = (context.project_context or {}).get("technology")
    stack = detect_task_stack(context.language, tech, text_signal=context.requirement)
    opts = DesignSystemOptions(
        agent_type="spec",
        rules_intro=_RULES_INTRO,
        task_stack=stack,
        is_revision=context.previous_spec is not None,
    )
    return build_design_system_content(components, context.project_context, opts)


def build_spec_messages(context: SpecPromptContext) -> list[ModelMessage]:
    """Constructs the system and user messages for SpecAgent."""
    return build_design_messages(_system_content(context), build_user_message(context))
