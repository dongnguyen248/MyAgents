"""Project skills shared by the agents, resolved into the run context.

Skills follow the open Agent Skills format (agentskills.io): one
folder per skill under the repository's ``skills/`` directory, each
holding a ``SKILL.md`` whose frontmatter carries the skill's ``name``
and a ``description`` stating what it does and when it applies.

ASF's agents do not browse a filesystem or self-select skills the
way an interactive coding agent does, so activation is the
platform's job, in two steps that mirror how project rules already
work: the assembly resolves the skills a project enables
(``enabledSkills`` in its profile) into the run context as
``context["project"]["skills"]`` — a list of ``{"id", "content"}``
with the frontmatter stripped — and each agent's prompt builder
appends the skills that apply to that agent (see ``SKILL_AGENTS``)
to its system prompt. Editing a SKILL.md therefore changes agent
behaviour on the next run, exactly like editing a rule file.

The applicability map is deliberately restrictive: a skill's tokens
are spent only on agents whose work it can change. The Test agent
runs no model, so its entry exists for display and future use; no
prompt ever includes it.
"""

from __future__ import annotations

import json
from typing import Any

# Skill id -> the agents the skill applies to (agent type keys).
SKILL_AGENTS: dict[str, frozenset[str]] = {
    "general": frozenset({"spec", "plan", "task", "implement", "review", "fix"}),
    "software-development": frozenset({"plan", "task", "implement", "review", "fix"}),
    "code-review": frozenset({"review", "fix"}),
    "testing": frozenset({"task", "implement", "review", "fix", "test"}),
    "security": frozenset({"spec", "implement", "review", "fix"}),
    "git": frozenset({"implement", "fix"}),
    "database": frozenset({"plan", "implement", "review", "fix"}),
    "java": frozenset({"plan", "implement", "review", "fix"}),
    "spring": frozenset({"plan", "implement", "review", "fix"}),
    "python": frozenset({"plan", "implement", "review", "fix"}),
    "react": frozenset({"plan", "implement", "review", "fix"}),
}

_SECTION_INTRO = (
    "Project skills — the project enables the skills below. Apply"
    " their guidance where it fits this task; where a skill conflicts"
    " with the output contract above, the output contract wins:"
)


def agent_skill_ids(agent_type: str) -> list[str]:
    """Catalogue skill ids that apply to an agent type, sorted."""
    return sorted(
        skill_id for skill_id, agents in SKILL_AGENTS.items()
        if agent_type in agents
    )


def _project_mapping(project: Any) -> dict[str, Any]:
    if isinstance(project, str):
        try:
            project = json.loads(project)
        except (ValueError, RecursionError):
            return {}
    return project if isinstance(project, dict) else {}


def skills_for_agent(project: Any, agent: str) -> list[tuple[str, str]]:
    """(id, content) pairs from the project context applying to `agent`."""
    entries = _project_mapping(project).get("skills")
    if not isinstance(entries, list):
        return []
    selected: list[tuple[str, str]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        skill_id = entry.get("id")
        content = entry.get("content")
        if (
            isinstance(skill_id, str) and isinstance(content, str)
            and content.strip() and agent in SKILL_AGENTS.get(skill_id, frozenset())
        ):
            selected.append((skill_id, content.strip()))
    return selected


def skills_section(project: Any, agent: str) -> str:
    """A system-prompt block with the agent's applicable skills, or ''."""
    selected = skills_for_agent(project, agent)
    if not selected:
        return ""
    blocks = "\n\n".join(
        f"### Skill: {skill_id}\n{content}" for skill_id, content in selected
    )
    return f"\n\n{_SECTION_INTRO}\n{blocks}"
