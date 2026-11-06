"""Convert between an agent's repo files and a harness Tree (H1).

The default components of an agent live in its package
(`src/asf/agents/<agent>/`): `prompts/contract.md`,
`prompts/system.md`, `prompts/revision.md` where one exists,
`instructions/guardrails.md`, `instructions/memory.md`,
`tools/tool_guidance.md` for the code agents, and agent-scoped
skills under `skills/<name>/SKILL.md` (none by default). Loading
goes through `importlib.resources`, the same mechanism the runtime
loaders use, so what the loop edits is what a packaged install
would run.
"""

from __future__ import annotations

import importlib.resources

from asf.agents._shared.harness import HarnessComponents
from harness.harness2.surface import (
    AGENT_SURFACES,
    CONTRACT_PATH,
    GUARDRAILS_PATH,
    MEMORY_PATH,
    REVISION_PATH,
    SYSTEM_PATH,
    TOOL_GUIDANCE_PATH,
    SurfaceSpec,
    Tree,
    validate_tree,
)

__all__ = [
    "AGENT_PACKAGES",
    "components_to_tree",
    "default_tree",
    "load_default_components",
    "tree_to_components",
    "validate_candidate",
]

AGENT_PACKAGES: dict[str, str] = {
    "spec": "asf.agents.spec",
    "plan": "asf.agents.plan",
    "task": "asf.agents.task",
    "implement": "asf.agents.implement",
    "review": "asf.agents.review",
    "fix": "asf.agents.fix",
}


def _read(package: str, relative: str) -> str | None:
    traversable = importlib.resources.files(package)
    for part in relative.split("/"):
        traversable = traversable.joinpath(part)
    if not traversable.is_file():
        return None
    return traversable.read_text(encoding="utf-8")


def _load_skills(package: str) -> dict[str, str]:
    skills: dict[str, str] = {}
    skills_dir = importlib.resources.files(package).joinpath("skills")
    if not skills_dir.is_dir():
        return skills
    for entry in sorted(skills_dir.iterdir(), key=lambda item: item.name):
        if not entry.is_dir():
            continue
        text = _read(package, f"skills/{entry.name}/SKILL.md")
        if text is not None:
            skills[entry.name] = text
    return skills


def load_default_components(agent: str) -> HarnessComponents:
    """The harness an agent runs with when nothing overrides it."""
    package = AGENT_PACKAGES[agent]
    return HarnessComponents(
        contract=_read(package, CONTRACT_PATH) or "",
        system=_read(package, SYSTEM_PATH) or "",
        revision=_read(package, REVISION_PATH) or "",
        guardrails=_read(package, GUARDRAILS_PATH) or "",
        memory=_read(package, MEMORY_PATH) or "",
        tool_guidance=_read(package, TOOL_GUIDANCE_PATH) or "",
        skills=_load_skills(package),
    )


def components_to_tree(components: HarnessComponents, agent: str) -> Tree:
    """Flatten components into surface paths for the agent."""
    spec = AGENT_SURFACES[agent]
    tree: Tree = {
        CONTRACT_PATH: components.contract,
        SYSTEM_PATH: components.system,
        GUARDRAILS_PATH: components.guardrails,
        MEMORY_PATH: components.memory,
    }
    if spec.has_revision:
        tree[REVISION_PATH] = components.revision
    if spec.has_tool_guidance:
        tree[TOOL_GUIDANCE_PATH] = components.tool_guidance
    for name, content in sorted(components.skills.items()):
        tree[f"skills/{name}/SKILL.md"] = content
    return tree


def tree_to_components(tree: Tree, agent: str) -> HarnessComponents:
    """Rebuild components from a tree (missing files read as empty)."""
    skills = {
        path.split("/")[1]: content
        for path, content in tree.items()
        if path.startswith("skills/") and path.endswith("/SKILL.md")
    }
    return HarnessComponents(
        contract=tree.get(CONTRACT_PATH, ""),
        system=tree.get(SYSTEM_PATH, ""),
        revision=tree.get(REVISION_PATH, ""),
        guardrails=tree.get(GUARDRAILS_PATH, ""),
        memory=tree.get(MEMORY_PATH, ""),
        tool_guidance=tree.get(TOOL_GUIDANCE_PATH, ""),
        skills=skills,
    )


def default_tree(agent: str) -> Tree:
    """The agent's current repo harness as a Tree (the base tree)."""
    return components_to_tree(load_default_components(agent), agent)


def validate_candidate(agent: str, tree: Tree, base: Tree | None = None) -> list[str]:
    """Validate a candidate tree against the agent's surface and base."""
    spec: SurfaceSpec = AGENT_SURFACES[agent]
    return validate_tree(tree, spec, base if base is not None else default_tree(agent))
