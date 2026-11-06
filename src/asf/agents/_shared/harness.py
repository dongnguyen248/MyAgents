"""The harness of an agent as an addressable object (Phase 11b, H1).

A harness is everything around the fixed model that shapes one
agent's behaviour: its contract and system prompt, revision prompt,
guardrails, memory, tool guidance and agent-scoped skills. Until H1
that text lived only inside each agent's prompt files, assembled
inline by its builder; now the components are a frozen value with a
fingerprint, so a run's outcomes can be attributed to the exact
harness that produced them (`Artifact.metadata["harnessFingerprint"]`)
and the offline Harness² loop can propose edits against a tree of
these components. See `docs/architecture/harness2.md`.

Assembly order (design decision D5): contract + system
(+ revision) + project rules section + guardrails + memory +
shared skills section + agent-scoped skills. The per-agent builders
own the rules/skills sections (their intro text differs per agent);
this module owns the component-derived parts. With guardrails,
memory and agent-scoped skills empty, assembly is byte-identical to
the pre-H1 builders — locked by `tests/golden/harness/`.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field

__all__ = [
    "HarnessComponents",
    "agent_skills_section",
    "assemble_base_prompt",
    "components_from_prompts",
    "fingerprint",
    "guardrails_memory_section",
]


@dataclass(frozen=True)
class HarnessComponents:
    """One agent's harness: the editable surface of design decision D5."""

    contract: str = ""
    system: str = ""
    revision: str = ""
    guardrails: str = ""
    memory: str = ""
    tool_guidance: str = ""
    skills: Mapping[str, str] = field(default_factory=dict)


def components_from_prompts(
    *,
    contract: str,
    system: str,
    revision: str = "",
    tool_guidance: str = "",
) -> HarnessComponents:
    """The components an agent's loaded prompts represent on their own."""
    return HarnessComponents(
        contract=contract,
        system=system,
        revision=revision,
        tool_guidance=tool_guidance,
    )


def assemble_base_prompt(components: HarnessComponents, *, revision: bool = False) -> str:
    """Contract + system (+ revision): the head of the system prompt."""
    base = components.contract + components.system
    if revision:
        base = f"{base}\n\n{components.revision}"
    return base


def guardrails_memory_section(components: HarnessComponents) -> str:
    """Guardrails then memory, verbatim; '' when both are empty."""
    parts = [text.strip() for text in (components.guardrails, components.memory) if text.strip()]
    if not parts:
        return ""
    return "\n\n" + "\n\n".join(parts)


def agent_skills_section(components: HarnessComponents) -> str:
    """Agent-scoped skills as `### Skill:` blocks; '' when none apply."""
    blocks = [
        f"### Skill: {name}\n{content.strip()}"
        for name, content in sorted(components.skills.items())
        if content.strip()
    ]
    if not blocks:
        return ""
    return "\n\n" + "\n\n".join(blocks)


def fingerprint(components: HarnessComponents) -> str:
    """Stable sha256 over every component; changes iff a component does."""
    payload = {
        "contract": components.contract,
        "system": components.system,
        "revision": components.revision,
        "guardrails": components.guardrails,
        "memory": components.memory,
        "tool_guidance": components.tool_guidance,
        "skills": dict(sorted(components.skills.items())),
    }
    text = json.dumps(payload, ensure_ascii=True, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
