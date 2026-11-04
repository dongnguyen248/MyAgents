from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from asf.agents._shared.rules import rules_section
from asf.agents.plan.milestones import (
    MAX_MILESTONES,
    Milestone,
    MilestoneValidationError,
    milestone_ancestors,
    parse_milestones,
)
from asf.contracts.models import ApprovalFeedback, ModelMessage

__all__ = [
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


@dataclass(frozen=True)
class PlanPrompts:
    system: str
    revision: str


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


def build_user_message(
    spec_artifact: dict[str, Any],
    language: str | None,
    project_context: dict[str, Any] | None,
    template_text: str,
    previous_plan: tuple[str, str] | None = None,
    feedback: Sequence[ApprovalFeedback] = (),
) -> str:
    """Builds the user prompt message with fixed sections."""
    sections: list[str] = []

    # 1. Linked SPEC (input artifact)
    spec_id = spec_artifact.get("id", "unknown")
    spec_version = spec_artifact.get("version", "unknown")
    spec_text = ""
    if isinstance(spec_artifact.get("content"), dict):
        spec_text = spec_artifact["content"].get("text", "")
    elif isinstance(spec_artifact.get("content"), str):
        spec_text = spec_artifact["content"]

    sections.append(f"## Linked SPEC\nID: {spec_id}\nVersion: {spec_version}\n\n{spec_text}")

    # 2. Output language
    lang_str = language if language else "same language as the SPEC"
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
    if previous_plan is not None:
        prev_version, prev_text = previous_plan
        sections.append(f"## Previous plan (version {prev_version})\n{prev_text}")

        feedback_lines = [
            f"- [{fb.decision}] {fb.reviewer}: {fb.comment}"
            for fb in feedback
        ]
        feedback_str = "\n".join(feedback_lines) if feedback_lines else "none"
        sections.append(f"## Reviewer feedback\n{feedback_str}")

    return "\n\n".join(sections)


def build_plan_messages(
    prompts: PlanPrompts,
    template: PlanTemplate,
    spec_artifact: dict[str, Any],
    language: str | None,
    project_context: dict[str, Any] | None,
    previous_plan: tuple[str, str] | None = None,
    feedback: Sequence[ApprovalFeedback] = (),
) -> list[ModelMessage]:
    """Constructs the system and user messages for PlanAgent."""
    is_revision = previous_plan is not None
    if is_revision:
        system_content = f"{prompts.system}\n\n{prompts.revision}"
    else:
        system_content = prompts.system
    system_content += rules_section(
        project_context,
        "Project development rules — the standards this project's code"
        " must follow. Design the plan so the implementation can comply"
        " with them (structure, layering, and the files and contracts the"
        " standards require); where they conflict with the output"
        " contract above, the output contract wins:",
    )

    user_content = build_user_message(
        spec_artifact=spec_artifact,
        language=language,
        project_context=project_context,
        template_text=template.text,
        previous_plan=previous_plan,
        feedback=feedback,
    )

    return [
        ModelMessage(role="system", content=system_content),
        ModelMessage(role="user", content=user_content),
    ]