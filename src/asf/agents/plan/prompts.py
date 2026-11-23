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
from asf.agents._shared.prompt_context import (
    linked_artifact_section,
    project_context_section,
    revision_sections,
)
from asf.agents._shared.rules import detect_task_stack
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
    tech = (context.project_context or {}).get("technology")
    spec_text = _artifact_text(context.spec_artifact)
    stack = detect_task_stack(context.language, tech, text_signal=spec_text)
    sections = [
        linked_artifact_section(context.spec_artifact, "Linked SPEC"),
        format_language_section(context.language),
        project_context_section(context.project_context, task_stack=stack),
        f"## Template\n{context.template.text}",
        *revision_sections(context.previous_plan, "Previous plan", context.feedback),
    ]
    return build_design_user_content(sections)


def _components(context: PlanPromptContext) -> HarnessComponents:
    if context.harness is not None:
        return context.harness
    return context.prompts.to_components()


def _artifact_text(artifact: Mapping[str, Any] | None) -> str:
    if not isinstance(artifact, dict):
        return ""
    content = artifact.get("content")
    if isinstance(content, dict):
        text = content.get("text")
        return text if isinstance(text, str) else ""
    return content if isinstance(content, str) else ""


def _system_content(context: PlanPromptContext) -> str:
    components = _components(context)
    tech = (context.project_context or {}).get("technology")
    spec_text = _artifact_text(context.spec_artifact)
    stack = detect_task_stack(context.language, tech, text_signal=spec_text)
    opts = DesignSystemOptions(
        agent_type="plan",
        rules_intro=_RULES_INTRO,
        task_stack=stack,
        is_revision=context.previous_plan is not None,
    )
    return build_design_system_content(components, context.project_context, opts)


def build_plan_messages(context: PlanPromptContext) -> list[ModelMessage]:
    """Constructs the system and user messages for PlanAgent."""
    return build_design_messages(_system_content(context), build_user_message(context))
