"""The editable harness surface of an agent (Phase 11b, design D5).

A harness `Tree` is a flat mapping of repo-relative paths (relative
to the agent's package directory) to file contents. The surface
spec says which paths exist, which are frozen, and the always-on
character cap. `validate_tree` is the candidate validator of the
algorithm spec: it returns every problem it finds, in prose, because
the messages are fed back to the improver verbatim (H3).

The leak tripwire and the secret scan apply to the files an improver
may write (system prompt, guardrails, memory, tool guidance, agent
skills). Frozen files are authored by ASF and legitimately name
artifact types (the Fix contract mentions `CODE_REVIEW`), so they
are checked for byte-identity against the base instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from asf.agents._shared.security import scan_secrets

__all__ = [
    "AGENT_SURFACES",
    "BANNED_PREFIXES",
    "CHECKLIST_PATHS",
    "CONTRACT_PATH",
    "GUARDRAILS_PATH",
    "LEAK_MARKERS",
    "MEMORY_PATH",
    "REVISION_PATH",
    "SYSTEM_PATH",
    "TOOL_GUIDANCE_PATH",
    "SurfaceSpec",
    "Tree",
    "diff_summary",
    "read_tree",
    "validate_tree",
    "write_tree",
]

Tree = dict[str, str]

CONTRACT_PATH = "prompts/contract.md"
SYSTEM_PATH = "prompts/system.md"
REVISION_PATH = "prompts/revision.md"
GUARDRAILS_PATH = "instructions/guardrails.md"
MEMORY_PATH = "instructions/memory.md"
TOOL_GUIDANCE_PATH = "tools/tool_guidance.md"
CHECKLIST_PATHS = (
    "instructions/checklist_spec.md",
    "instructions/checklist_plan.md",
    "instructions/checklist_task.md",
)

LEAK_MARKERS = ("CHANGES_REQUESTED", "TEST_REPORT", "CODE_REVIEW")
BANNED_PREFIXES = ("scripts/", "subagents/", "plugins/")
SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_SKILL_PATH_PATTERN = re.compile(r"^skills/([^/]+)/SKILL\.md$")


@dataclass(frozen=True)
class SurfaceSpec:
    """One agent's harness surface: paths, caps, frozen lines.

    `always_on_max` is the D5 cap on the assembled system prompt.
    `tree_max` is what the validator can enforce offline: the cap
    minus the measured project overhead (rules + shared skills +
    builder intro text) from the H1 measurement in
    `docs/architecture/harness2.md`.
    """

    agent: str
    always_on_max: int
    tree_max: int
    has_revision: bool
    has_tool_guidance: bool
    frozen_lines: tuple[str, ...] = ()
    extra_editable: tuple[str, ...] = ()

    def fixed_paths(self) -> dict[str, bool]:
        """Known non-skill paths mapped to their frozen flag."""
        paths = {
            CONTRACT_PATH: True,
            SYSTEM_PATH: False,
            GUARDRAILS_PATH: False,
            MEMORY_PATH: False,
        }
        if self.has_revision:
            paths[REVISION_PATH] = True
        if self.has_tool_guidance:
            paths[TOOL_GUIDANCE_PATH] = False
        for path in self.extra_editable:
            paths[path] = False
        return paths

    def editable_paths(self) -> set[str]:
        return {path for path, frozen in self.fixed_paths().items() if not frozen}


AGENT_SURFACES: dict[str, SurfaceSpec] = {
    "spec": SurfaceSpec(
        agent="spec",
        always_on_max=57_000,
        tree_max=20_714,
        has_revision=True,
        has_tool_guidance=False,
        frozen_lines=("Return only the final markdown document.",),
    ),
    "plan": SurfaceSpec(
        agent="plan",
        always_on_max=80_000,
        tree_max=29_273,
        has_revision=True,
        has_tool_guidance=False,
        frozen_lines=(
            "Milestone IDs must be unique and sequential",
            "must reference the provided SPEC artifact ID and version verbatim",
            "Return only the final markdown document.",
        ),
    ),
    "task": SurfaceSpec(
        agent="task",
        always_on_max=67_000,
        tree_max=25_151,
        has_revision=True,
        has_tool_guidance=False,
        frozen_lines=(
            "Return ONLY the JSON envelope",
            "Task IDs must be unique and sequential",
            "expectedFiles: relative paths only",
        ),
    ),
    "implement": SurfaceSpec(
        agent="implement",
        always_on_max=88_000,
        tree_max=30_807,
        has_revision=False,
        has_tool_guidance=True,
        frozen_lines=(
            "Only modify files listed in the task item's Expected Files.",
            "No secrets in generated content",
            "Empty change set is not allowed.",
            "Return ONLY the requested output format",
        ),
    ),
    "review": SurfaceSpec(
        agent="review",
        always_on_max=89_000,
        tree_max=30_812,
        has_revision=False,
        has_tool_guidance=False,
    ),
    "fix": SurfaceSpec(
        agent="fix",
        always_on_max=93_000,
        tree_max=33_336,
        has_revision=False,
        has_tool_guidance=True,
    ),
    "artifact-review": SurfaceSpec(
        agent="artifact-review",
        always_on_max=61_000,
        tree_max=24_195,
        has_revision=False,
        has_tool_guidance=False,
        extra_editable=CHECKLIST_PATHS,
    ),
}


def _skill_name(path: str) -> str | None:
    match = _SKILL_PATH_PATTERN.match(path)
    return match.group(1) if match else None


def _path_error(path: str, spec: SurfaceSpec) -> str | None:
    if path.startswith(BANNED_PREFIXES):
        return (
            f"{path}: scripts, subagents and plugins are not harness "
            "components in ASF (design rule 6: agents never perform "
            "side effects, and ASF has no subagent concept)."
        )
    if path in spec.fixed_paths():
        return None
    name = _skill_name(path)
    if name is None:
        return f"{path}: this path is not on the harness surface for agent '{spec.agent}'."
    if not SKILL_NAME_PATTERN.match(name):
        return f"{path}: skill name '{name}' must match [a-z0-9][a-z0-9_-]*."
    return None


def _path_errors(tree: Tree, spec: SurfaceSpec) -> list[str]:
    errors = [error for path in sorted(tree) if (error := _path_error(path, spec)) is not None]
    for path in sorted(spec.fixed_paths()):
        if path not in tree:
            errors.append(f"{path}: required harness file is missing from the tree.")
    return errors


def _frozen_errors(tree: Tree, base: Tree, spec: SurfaceSpec) -> list[str]:
    errors: list[str] = []
    for path, frozen in sorted(spec.fixed_paths().items()):
        if frozen and path in tree and path in base and tree[path] != base[path]:
            errors.append(f"{path}: this file is frozen and must stay byte-identical.")
    system = tree.get(SYSTEM_PATH, "")
    for line in spec.frozen_lines:
        if line not in system:
            errors.append(
                f"{SYSTEM_PATH}: the enforced sentence starting '{line[:60]}' "
                "was removed or reworded; it is enforced by a code validator "
                "and must stay verbatim (see docs/architecture/harness2.md)."
            )
    return errors


def _marker_errors(path: str, content: str) -> list[str]:
    return [
        f"{path}: contains the score marker '{marker}'; harness "
        "files must describe the work, never its measurement."
        for marker in LEAK_MARKERS
        if marker in content
    ]


def _content_errors(tree: Tree, spec: SurfaceSpec) -> list[str]:
    errors: list[str] = []
    editable = spec.editable_paths()
    for path in sorted(tree):
        content = tree[path]
        if scan_secrets(content, path):
            errors.append(
                f"{path}: content matches a secret pattern; secrets never enter a harness."
            )
        if path in editable or _skill_name(path) is not None:
            errors.extend(_marker_errors(path, content))
    return errors


def _size_errors(tree: Tree, spec: SurfaceSpec) -> list[str]:
    total = sum(len(content) for content in tree.values())
    if total <= spec.tree_max:
        return []
    return [
        f"harness tree text is {total} chars, over the tree budget of "
        f"{spec.tree_max} for agent '{spec.agent}' (assembled cap "
        f"{spec.always_on_max} minus measured project overhead)."
    ]


def validate_tree(tree: Tree, spec: SurfaceSpec, base: Tree) -> list[str]:
    """Every problem with a candidate tree, in prose (empty = valid)."""
    return [
        *_path_errors(tree, spec),
        *_frozen_errors(tree, base, spec),
        *_content_errors(tree, spec),
        *_size_errors(tree, spec),
    ]


def read_tree(root: Path, spec: SurfaceSpec) -> Tree:
    """Read an agent's harness files from a directory into a Tree."""
    tree: Tree = {}
    for path in sorted(spec.fixed_paths()):
        file_path = root / path
        if file_path.is_file():
            tree[path] = file_path.read_text(encoding="utf-8")
    skills_dir = root / "skills"
    if skills_dir.is_dir():
        for skill_file in sorted(skills_dir.glob("*/SKILL.md")):
            relative = skill_file.relative_to(root).as_posix()
            tree[relative] = skill_file.read_text(encoding="utf-8")
    return tree


def write_tree(root: Path, tree: Tree) -> None:
    """Write a Tree under a directory, creating folders as needed."""
    for path, content in sorted(tree.items()):
        file_path = root / path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")


def _diff_line(path: str, before: Tree, after: Tree) -> str | None:
    if path not in before:
        return f"{path}: added ({len(after[path])} chars)"
    if path not in after:
        return f"{path}: removed ({len(before[path])} chars)"
    if before[path] == after[path]:
        return None
    delta = len(after[path]) - len(before[path])
    return f"{path}: changed ({delta:+d} chars)"


def diff_summary(before: Tree, after: Tree) -> list[str]:
    """One line per changed path: added, removed, or char delta."""
    paths = sorted(set(before) | set(after))
    return [line for path in paths if (line := _diff_line(path, before, after)) is not None]
