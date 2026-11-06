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
from asf.agents._shared.prompt_context import (
    linked_artifact_section,
    project_context_section,
    revision_sections,
)
from asf.agents._shared.rules import rules_section
from asf.agents._shared.skills import skills_section
from asf.agents.plan.milestones import (
    MAX_MILESTONES,
    Milestone,
    MilestoneValidationError,
    milestone_ancestors,
    parse_milestones,
)
from asf.contracts.models import ApprovalFeedback, ModelMessage

__all__ = [
    "PlanPromptContext",
    "PlanPrompts",
    "PlanTemplate",
    "build_plan_messages",
    "build_user_message",
    "validate_milestones",
    "parse_milestones",
    "milestone_ancestors",
    "MilestoneValidationError",
    "Milestone",
    "MAX_MILESTONES",
]

_RULES_INTRO = (
    "Project development rules — the standards this project's code"
    " must follow. Design the plan so the implementation can comply"
    " with them (structure, layering, and the files and contracts the"
    " standards require); where they conflict with the output"
    " contract above, the output contract wins:"
)


@dataclass(frozen=True)
class PlanPrompts:
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
class PlanTemplate:
    text: str
    required_sections: list[str]

    @classmethod
    def from_text(cls, text: str) -> PlanTemplate:
        sections: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("## "):
                sections.append(stripped)
        return cls(text=text, required_sections=sections)


@dataclass(frozen=True)
class PlanPromptContext:
    prompts: PlanPrompts
    template: PlanTemplate
    spec_artifact: dict[str, Any]
    language: str | None
    project_context: dict[str, Any] | None
    previous_plan: tuple[str, str] | None = None
    feedback: Sequence[ApprovalFeedback] = ()
    harness: HarnessComponents | None = None


def validate_milestones(plan_text: str) -> None:
    """Validates milestone structure in the PLAN markdown.

    Validates:
    - Milestone IDs are unique and sequential (M1, M2, ...)
    - Max milestone count (MAX_MILESTONES)
    - Every milestone has Deliverables, Acceptance criteria, Depends on fields
    - Depends on references only existing earlier milestones (no cycles possible by construction)
    - No self-dependencies (M1 depends on M1)
    """
    parse_milestones(plan_text)  # raises MilestoneValidationError on issues


def build_user_message(context: PlanPromptContext) -> str:
    """Builds the user prompt message with fixed sections."""
    language = context.language
    lang_str = language if language else "same language as the SPEC"
    sections = [
        linked_artifact_section(context.spec_artifact, "Linked SPEC"),
        f"## Output language\n{lang_str}",
        project_context_section(context.project_context),
        f"## Template\n{context.template.text}",
        *revision_sections(context.previous_plan, "Previous plan", context.feedback),
    ]
    return "\n\n".join(sections)


def _components(context: PlanPromptContext) -> HarnessComponents:
    if context.harness is not None:
        return context.harness
    return context.prompts.to_components()


def _system_content(context: PlanPromptContext) -> str:
    components = _components(context)
    content = assemble_base_prompt(components, revision=context.previous_plan is not None)
    content += rules_section(context.project_context, _RULES_INTRO)
    content += guardrails_memory_section(components)
    content += skills_section(context.project_context, "plan")
    content += agent_skills_section(components)
    return content


def build_plan_messages(context: PlanPromptContext) -> list[ModelMessage]:
    """Constructs the system and user messages for PlanAgent."""
    return [
        ModelMessage(role="system", content=_system_content(context)),
        ModelMessage(role="user", content=build_user_message(context)),
    ]
