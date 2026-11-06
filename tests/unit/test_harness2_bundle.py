"""Tests for the harness surface validator and repo<->Tree bundle (Phase 11b, H1)."""

from __future__ import annotations

from pathlib import Path

from asf.agents._shared.harness import fingerprint
from harness.harness2.bundle import (
    components_to_tree,
    default_tree,
    load_default_components,
    tree_to_components,
    validate_candidate,
)
from harness.harness2.surface import (
    AGENT_SURFACES,
    CONTRACT_PATH,
    GUARDRAILS_PATH,
    SYSTEM_PATH,
    diff_summary,
    read_tree,
    write_tree,
)

AGENTS = ["spec", "plan", "task", "implement", "review", "fix"]


def test_round_trip_for_every_agent():
    for agent in AGENTS:
        components = load_default_components(agent)
        tree = components_to_tree(components, agent)
        assert tree_to_components(tree, agent) == components


def test_default_trees_validate_clean():
    for agent in AGENTS:
        assert validate_candidate(agent, default_tree(agent)) == []


def test_default_components_match_runtime_prompts():
    components = load_default_components("review")
    assert "APPROVE" in components.contract
    assert components.system == ""
    spec = load_default_components("spec")
    assert "senior business analyst" in spec.contract
    assert spec.guardrails == ""
    assert spec.memory == ""
    assert spec.skills == {}


def test_fingerprint_of_default_components_is_stable():
    for agent in AGENTS:
        first = fingerprint(load_default_components(agent))
        second = fingerprint(load_default_components(agent))
        assert first == second


def test_off_surface_file_is_rejected():
    tree = default_tree("spec")
    tree["prompts/evil.md"] = "surprise"
    errors = validate_candidate("spec", tree)
    assert any("not on the harness surface" in error for error in errors)


def test_frozen_contract_edit_is_rejected():
    tree = default_tree("spec")
    tree[CONTRACT_PATH] = tree[CONTRACT_PATH] + "Edited."
    errors = validate_candidate("spec", tree)
    assert any("frozen" in error for error in errors)


def test_over_cap_tree_is_rejected():
    tree = default_tree("spec")
    tree[GUARDRAILS_PATH] = "x" * (AGENT_SURFACES["spec"].tree_max + 1)
    errors = validate_candidate("spec", tree)
    assert any("over the tree budget" in error for error in errors)


def test_secret_in_editable_file_is_rejected():
    tree = default_tree("spec")
    tree[GUARDRAILS_PATH] = "note: password = 'sup3rsecretvalue9'"
    errors = validate_candidate("spec", tree)
    assert any("secret pattern" in error for error in errors)


def test_script_path_is_rejected():
    tree = default_tree("spec")
    tree["scripts/run.py"] = "print('hi')"
    errors = validate_candidate("spec", tree)
    assert any("scripts, subagents and plugins" in error for error in errors)


def test_bad_skill_name_is_rejected():
    tree = default_tree("spec")
    tree["skills/Bad Name/SKILL.md"] = "body"
    errors = validate_candidate("spec", tree)
    assert any("skill name" in error for error in errors)


def test_agent_skill_round_trip_and_validation():
    components = load_default_components("implement")
    from dataclasses import replace

    with_skill = replace(components, skills={"tdd": "Write the test first."})
    tree = components_to_tree(with_skill, "implement")
    assert tree["skills/tdd/SKILL.md"] == "Write the test first."
    assert validate_candidate("implement", tree) == []
    assert tree_to_components(tree, "implement").skills == {"tdd": "Write the test first."}


def test_frozen_line_removal_is_rejected():
    tree = default_tree("spec")
    tree[SYSTEM_PATH] = tree[SYSTEM_PATH].replace(
        "Return only the final markdown document.", "Return the document."
    )
    errors = validate_candidate("spec", tree)
    assert any("enforced sentence" in error for error in errors)


def test_leak_marker_in_editable_file_is_rejected():
    tree = default_tree("spec")
    tree[GUARDRAILS_PATH] = "Aim for a CHANGES_REQUESTED outcome."
    errors = validate_candidate("spec", tree)
    assert any("score marker" in error for error in errors)


def test_missing_required_file_is_rejected():
    tree = default_tree("plan")
    del tree[SYSTEM_PATH]
    errors = validate_candidate("plan", tree)
    assert any("missing" in error for error in errors)


def test_read_write_tree_round_trip(tmp_path: Path):
    spec = AGENT_SURFACES["fix"]
    tree = default_tree("fix")
    write_tree(tmp_path, tree)
    assert read_tree(tmp_path, spec) == tree


def test_diff_summary_reports_changes():
    before = default_tree("spec")
    after = dict(before)
    after[GUARDRAILS_PATH] = "New guardrail."
    after["skills/notes/SKILL.md"] = "body"
    lines = diff_summary(before, after)
    assert any(GUARDRAILS_PATH in line and "changed" in line for line in lines)
    assert any("skills/notes/SKILL.md" in line and "added" in line for line in lines)
