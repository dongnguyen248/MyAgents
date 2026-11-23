"""Shared prompt builder for design agents (spec, plan, task).

Consolidates system prompt assembly (rules filtering, stack matching, skill
digests, and character budgets) and user prompt assembly (omitting redundant
empty/default blocks).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from asf.agents._shared.harness import (
    HarnessComponents,
    agent_skills_section,
    assemble_base_prompt,
    guardrails_memory_section,
)
from asf.agents._shared.rules import (
    MAX_DESIGN_RULES_BUDGET,
    RulesFilterOptions,
    detect_task_stack,
    rules_section,
)
from asf.agents._shared.skills import skills_section
from asf.contracts.models import ModelMessage


@dataclass(frozen=True)
class DesignSystemOptions:
    agent_type: str
    rules_intro: str
    task_stack: frozenset[str] | None = None
    is_revision: bool = False
    budget: int = MAX_DESIGN_RULES_BUDGET


def format_language_section(language: str | None) -> str:
    """Formats ## Output language only when an explicit language is configured."""
    if language and language.strip():
        return f"## Output language\n{language.strip()}"
    return ""


def build_design_system_content(
    components: HarnessComponents,
    project_context: dict[str, Any] | None,
    opts: DesignSystemOptions,
) -> str:
    """Assembles system prompt with stack-filtered rules and skill digests."""
    stack = opts.task_stack
    if stack is None and project_context:
        tech = project_context.get("technology") or project_context.get("technologies")
        stack = detect_task_stack(None, tech)
    content = assemble_base_prompt(components, revision=opts.is_revision)
    filter_opts = RulesFilterOptions(agent=opts.agent_type, stack=stack, budget=opts.budget)
    content += rules_section(project_context, opts.rules_intro, filter_opts)
    content += guardrails_memory_section(components)
    content += skills_section(project_context, opts.agent_type, stack)
    content += agent_skills_section(components)
    return content


def build_design_user_content(sections: Sequence[str]) -> str:
    """Joins non-empty sections into a clean user prompt."""
    non_empty = [s.strip() for s in sections if s and s.strip()]
    return "\n\n".join(non_empty)


def build_design_messages(
    system_text: str,
    user_text: str,
) -> list[ModelMessage]:
    """Wraps system and user prompt strings into ModelMessage list."""
    return [
        ModelMessage(role="system", content=system_text),
        ModelMessage(role="user", content=user_text),
    ]
