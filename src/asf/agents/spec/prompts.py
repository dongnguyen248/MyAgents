from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from asf.agents._shared.harness import (
    HarnessComponents,
    agent_skills_section,
    assemble_base_prompt,
    guardrails_memory_section,
)
from asf.agents._shared.prompt_context import project_context_section, revision_sections
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
    language = context.language
    lang_str = language if language else "same language as the requirement"
    sections = [
        f"## Requirement\n{context.requirement}",
        f"## Output language\n{lang_str}",
        project_context_section(context.project_context),
        f"## Template\n{context.template.text}",
        *revision_sections(context.previous_spec, "Previous specification", context.feedback),
    ]
    return "\n\n".join(sections)


def _components(context: SpecPromptContext) -> HarnessComponents:
    if context.harness is not None:
        return context.harness
    return context.prompts.to_components()


def _system_content(context: SpecPromptContext) -> str:
    components = _components(context)
    content = assemble_base_prompt(components, revision=context.previous_spec is not None)
    content += rules_section(context.project_context, _RULES_INTRO)
    content += guardrails_memory_section(components)
    content += skills_section(context.project_context, "spec")
    content += agent_skills_section(components)
    return content


def build_spec_messages(context: SpecPromptContext) -> list[ModelMessage]:
    """Constructs the system and user messages for SpecAgent."""
    return [
        ModelMessage(role="system", content=_system_content(context)),
        ModelMessage(role="user", content=build_user_message(context)),
    ]
