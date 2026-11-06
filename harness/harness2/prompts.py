"""Improver prompt templates: loading, filling, wording checks (H3).

One text file per mission lives in `prompts/` next to this module
(`select` and `experience` join in H4). The templates describe the
work only — never its measurement — and `load_prompt` refuses a
template that mentions measurement, the same wording discipline
the method requires of the prompts themselves. Filling is a single
pass over `{placeholder}` tokens, so text inserted from evidence
or harness files is never rescanned for placeholders.
"""

from __future__ import annotations

import importlib.resources
import re
from collections.abc import Mapping
from dataclasses import dataclass

from harness.harness2.surface import AGENT_SURFACES, Tree

__all__ = [
    "FORBIDDEN_MEASUREMENT_WORDS",
    "PROMPT_NAMES",
    "MissionInputs",
    "check_prompt_text",
    "decisions_text",
    "harness_text",
    "load_prompt",
    "mission_prompt",
    "surface_text",
]

PROMPT_NAMES = ("propose_inv", "propose_dom", "aggregate", "compose_round")
FORBIDDEN_MEASUREMENT_WORDS = ("benchmark", "evaluation", "grader", "rubric", "score")
_PLACEHOLDER_PATTERN = re.compile(r"\{(agent|surface|evidence|harness|decisions)\}")


def check_prompt_text(name: str, text: str) -> None:
    """Refuse prompt text that mentions measurement (method rule)."""
    lowered = text.lower()
    found = [word for word in FORBIDDEN_MEASUREMENT_WORDS if word in lowered]
    if found:
        raise ValueError(
            f"improver prompt '{name}' mentions measurement ({', '.join(found)}); "
            "prompts describe the work, never its measurement"
        )


def load_prompt(name: str) -> str:
    """Load one mission template, wording check applied."""
    if name not in PROMPT_NAMES:
        raise ValueError(f"unknown improver prompt '{name}'")
    resource = importlib.resources.files("harness.harness2").joinpath("prompts", f"{name}.md")
    text = resource.read_text(encoding="utf-8")
    check_prompt_text(name, text)
    return text


def surface_text(agent: str) -> str:
    """The editable/frozen listing + size budget for one agent."""
    spec = AGENT_SURFACES[agent]
    editable = "\n".join(f"- {path}" for path in sorted(spec.editable_paths()))
    frozen = "\n".join(
        f"- {path}" for path, is_frozen in sorted(spec.fixed_paths().items()) if is_frozen
    )
    return (
        f"Editable files (you may change these):\n{editable}\n\n"
        f"Frozen files (shown for context; they must stay byte-identical):\n{frozen}\n\n"
        "New agent-scoped skills may be created at skills/<name>/SKILL.md "
        "(lowercase name: letters, digits, '-' and '_').\n"
        f"The whole harness tree may hold at most {spec.tree_max} characters of text."
    )


def harness_text(tree: Tree) -> str:
    """The current harness files, delimited, in path order."""
    return "\n\n".join(f"===== {path} =====\n{tree[path]}" for path in sorted(tree))


def decisions_text(decisions: Mapping[str, str] | None) -> str:
    """Candidate-stage notes for a composition prompt."""
    if not decisions:
        return "(no candidate session reported notes)"
    return "\n".join(f"- {label}: {note}" for label, note in sorted(decisions.items()))


@dataclass(frozen=True)
class MissionInputs:
    """Everything one improver session's prompt is filled from."""

    agent: str
    evidence: str
    harness: Tree
    decisions: Mapping[str, str] | None = None


def mission_prompt(name: str, inputs: MissionInputs) -> str:
    """Fill one mission template with the session's inputs."""
    values = {
        "agent": inputs.agent,
        "surface": surface_text(inputs.agent),
        "evidence": inputs.evidence,
        "harness": harness_text(inputs.harness),
        "decisions": decisions_text(inputs.decisions),
    }
    return _PLACEHOLDER_PATTERN.sub(lambda match: values[match.group(1)], load_prompt(name))
