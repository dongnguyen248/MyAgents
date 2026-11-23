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
import logging
from typing import Any

logger = logging.getLogger(__name__)

DESIGN_AGENTS: frozenset[str] = frozenset({"spec", "plan", "task"})

_STACK_SKILLS: dict[str, str] = {
    "python": "python",
    "react": "typescript",
    "java": "java",
    "spring": "java",
}

# Skill id -> the agents the skill applies to (agent type keys).
SKILL_AGENTS: dict[str, frozenset[str]] = {
    "general": frozenset({"spec", "plan", "task", "implement", "review", "fix"}),
    "software-development": frozenset({"plan", "task", "implement", "review", "fix"}),
    "code-review": frozenset({"review", "fix"}),
    "code-structure": frozenset({"plan", "task", "implement", "review", "fix"}),
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
    return sorted(skill_id for skill_id, agents in SKILL_AGENTS.items() if agent_type in agents)


def _project_mapping(project: Any) -> dict[str, Any]:
    if isinstance(project, str):
        try:
            project = json.loads(project)
        except (ValueError, RecursionError):
            return {}
    return project if isinstance(project, dict) else {}


def _is_skill_stack_allowed(skill_id: str, stack: frozenset[str] | None) -> bool:
    if stack is None or skill_id not in _STACK_SKILLS:
        return True
    return _STACK_SKILLS[skill_id] in stack


def _is_entry_valid(entry: Any, agent: str, stack: frozenset[str] | None) -> str | None:
    if not isinstance(entry, dict):
        return None
    skill_id = entry.get("id")
    if not isinstance(skill_id, str) or agent not in SKILL_AGENTS.get(skill_id, frozenset()):
        return None
    if not _is_skill_stack_allowed(skill_id, stack):
        return None
    return skill_id


def _extract_skill_entry(
    entry: Any,
    agent: str,
    stack: frozenset[str] | None,
) -> tuple[str, str] | None:
    skill_id = _is_entry_valid(entry, agent, stack)
    if skill_id is None:
        return None
    if agent in DESIGN_AGENTS:
        digest = entry.get("digest")
        if isinstance(digest, str) and digest.strip():
            return (skill_id, digest.strip())
        logger.warning(
            "Skill '%s' has no digest; omitting from design agent '%s'",
            skill_id,
            agent,
        )
        return None
    content = entry.get("content")
    if isinstance(content, str) and content.strip():
        return (skill_id, content.strip())
    return None


def extract_skill_digest(text: str) -> str | None:
    """Extracts the digest line from SKILL.md frontmatter, or None."""
    stripped = text.lstrip()
    if not stripped.startswith("---"):
        return None
    lines = stripped.splitlines()
    for index in range(1, len(lines)):
        line = lines[index].strip()
        if line == "---":
            break
        if line.startswith("digest:"):
            digest = line[len("digest:") :].strip()
            return digest if digest else None
    return None


def skills_for_agent(
    project: Any,
    agent: str,
    stack: frozenset[str] | None = None,
) -> list[tuple[str, str]]:
    """(id, content_or_digest) pairs from project context applying to `agent`."""
    entries = _project_mapping(project).get("skills")
    if not isinstance(entries, list):
        return []
    selected: list[tuple[str, str]] = []
    for entry in entries:
        item = _extract_skill_entry(entry, agent, stack)
        if item is not None:
            selected.append(item)
    return selected


def skills_section(
    project: Any,
    agent: str,
    stack: frozenset[str] | None = None,
) -> str:
    """A system-prompt block with the agent's applicable skills, or ''."""
    selected = skills_for_agent(project, agent, stack)
    if not selected:
        return ""
    blocks = "\n\n".join(f"### Skill: {skill_id}\n{content}" for skill_id, content in selected)
    return f"\n\n{_SECTION_INTRO}\n{blocks}"
