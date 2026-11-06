"""The artifact-review agent is registered on the Harness surface.

Registration contract (Phase 12, Stage E): the editable files are the
system prompt, guardrails, memory, agent skills, and the three stage
checklists. `prompts/contract.md` is frozen, and the agent's Python
modules (verdict.py, checks.py) are not harness files at all, so no
candidate tree may carry them. Data only: the optimiser is not run.
"""

from __future__ import annotations

import importlib.resources
from pathlib import Path

from harness.harness2.bundle import AGENT_PACKAGES, default_tree, validate_candidate
from harness.harness2.surface import (
    AGENT_SURFACES,
    CHECKLIST_PATHS,
    CONTRACT_PATH,
    GUARDRAILS_PATH,
    MEMORY_PATH,
    SYSTEM_PATH,
    read_tree,
)

EDITABLE = {SYSTEM_PATH, GUARDRAILS_PATH, MEMORY_PATH, *CHECKLIST_PATHS}


def test_surface_registration() -> None:
    spec = AGENT_SURFACES["artifact-review"]
    assert AGENT_PACKAGES["artifact-review"] == "asf.agents.artifact_review"
    assert spec.editable_paths() == EDITABLE
    assert spec.fixed_paths()[CONTRACT_PATH] is True
    assert not spec.has_revision
    assert not spec.has_tool_guidance


def test_default_tree_is_valid_and_matches_the_package_files() -> None:
    tree = default_tree("artifact-review")
    assert set(tree) == EDITABLE | {CONTRACT_PATH}
    assert validate_candidate("artifact-review", tree) == []
    package_dir = Path(str(importlib.resources.files(AGENT_PACKAGES["artifact-review"])))
    assert read_tree(package_dir, AGENT_SURFACES["artifact-review"]) == tree


def test_contract_is_frozen_and_python_modules_are_off_surface() -> None:
    tree = default_tree("artifact-review")
    edited = dict(tree)
    edited[CONTRACT_PATH] = tree[CONTRACT_PATH] + "\nEdited.\n"
    errors = validate_candidate("artifact-review", edited)
    assert any("frozen" in error for error in errors)
    for path in ("verdict.py", "checks.py"):
        candidate = dict(tree)
        candidate[path] = "x"
        errors = validate_candidate("artifact-review", candidate)
        assert any("not on the harness surface" in error for error in errors), path


def test_checklists_are_editable() -> None:
    tree = default_tree("artifact-review")
    for path in CHECKLIST_PATHS:
        candidate = dict(tree)
        candidate[path] = tree[path] + "\n- One more check.\n"
        assert validate_candidate("artifact-review", candidate) == [], path
