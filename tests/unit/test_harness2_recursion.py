"""Tests for the Harness² task-level recursion structure (Phase 11b, H2)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from harness.harness2.context import EvidenceBundle, build_evidence
from harness.harness2.ledger import Ledger, expected_rollouts, expected_sessions
from harness.harness2.recursion import Loop, StageRequest, run_parallel, run_sequential, run_stage
from harness.harness2.surface import Tree

BASE_TREE: Tree = {"prompts/system.md": "base system", "prompts/contract.md": "contract"}


class FakeAdapter:
    agent_type = "spec"

    def __init__(self, runs_root: Path, *, die_on: frozenset[str] = frozenset()) -> None:
        self._root = runs_root
        self._die_on = die_on
        self.executions = 0

    def tasks(self) -> list[str]:
        return ["t1"]

    def domain_of(self, task_id: str) -> str:
        return "python"

    def task_input(self, task_id: str) -> Any:
        raise NotImplementedError

    def base_harness(self) -> Tree:
        return dict(BASE_TREE)

    def validate_tree(self, tree: Tree) -> None:
        if tree.get("prompts/system.md", "").endswith("BAD"):
            raise ValueError("system prompt must not end with BAD")

    def execute(self, task_id: str, harness: Tree | None, run_id: str) -> Path:
        self.executions += 1
        if run_id in self._die_on:
            raise RuntimeError("rollout died")
        run_dir = self._root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        system = (harness or BASE_TREE)["prompts/system.md"]
        delivered = "marker" in system
        (run_dir / "result.json").write_text(json.dumps({"delivered": delivered}))
        (run_dir / "trajectory.txt").write_text(f"system was: {system}")
        return run_dir

    def delivered(self, run_dir: Path) -> bool:
        return bool(json.loads((run_dir / "result.json").read_text())["delivered"])

    def trajectory(self, run_dir: Path, *, obs_trunc: int) -> str:
        return (run_dir / "trajectory.txt").read_text()

    def deliverable_text(self, run_dir: Path) -> str:
        return "deliverable" if self.delivered(run_dir) else ""

    def score(self, run_dir: Path, task_id: str) -> dict | None:
        return {"completion": 1.0}


class MarkerImprover:
    def improve(self, mission: str, evidence: EvidenceBundle, harness: Tree) -> Tree:
        tree = dict(harness)
        if "marker" not in tree["prompts/system.md"]:
            tree["prompts/system.md"] += " marker"
        return tree


class FlakyImprover:
    def __init__(self) -> None:
        self.calls = 0

    def improve(self, mission: str, evidence: EvidenceBundle, harness: Tree) -> Tree:
        self.calls += 1
        tree = dict(harness)
        tree["prompts/system.md"] += "BAD" if self.calls == 1 else " marker"
        return tree


class AlwaysBadImprover:
    def improve(self, mission: str, evidence: EvidenceBundle, harness: Tree) -> Tree:
        tree = dict(harness)
        tree["prompts/system.md"] += "BAD"
        return tree


def _evidence() -> EvidenceBundle:
    return build_evidence("t1", [])


@pytest.mark.parametrize("mode", ["parallel", "sequential"])
@pytest.mark.parametrize("k", [1, 2, 3])
def test_budget_identity_holds(tmp_path: Path, mode: str, k: int) -> None:
    adapter = FakeAdapter(tmp_path)
    run = run_parallel if mode == "parallel" else run_sequential
    result = run(adapter, "t1", k=k, improver=MarkerImprover())
    assert len(result.ledger.rollouts) == expected_rollouts(k)
    assert len(result.ledger.sessions) == expected_sessions(k)
    assert len(result.finals) == k
    assert all(final.delivered for final in result.finals)


def test_dead_rollout_is_recorded_and_run_continues(tmp_path: Path) -> None:
    adapter = FakeAdapter(tmp_path, die_on=frozenset({"t1-inv0"}))
    result = run_parallel(adapter, "t1", k=1, improver=MarkerImprover())
    assert result.ledger.dead_rollouts == ["inv0"]
    assert result.finals[0].delivered


def test_stage_retries_once_with_validator_feedback() -> None:
    adapter = FakeAdapter(Path("/unused"))
    improver = FlakyImprover()
    loop = Loop(adapter=adapter, improver=improver, ledger=Ledger())
    stage = run_stage(loop, StageRequest("inv0", "invariant", _evidence(), dict(BASE_TREE)))
    assert stage.attempts == 2
    assert stage.fell_back is False
    assert "marker" in stage.tree["prompts/system.md"]


def test_stage_falls_back_after_second_rejection() -> None:
    adapter = FakeAdapter(Path("/unused"))
    loop = Loop(adapter=adapter, improver=AlwaysBadImprover(), ledger=Ledger())
    stage = run_stage(loop, StageRequest("inv0", "invariant", _evidence(), dict(BASE_TREE)))
    assert stage.fell_back is True
    assert stage.tree == BASE_TREE


def test_stage_marks_noop_as_kept_base() -> None:
    adapter = FakeAdapter(Path("/unused"))

    class NoopImprover:
        def improve(self, mission: str, evidence: EvidenceBundle, harness: Tree) -> Tree:
            return dict(harness)

    loop = Loop(adapter=adapter, improver=NoopImprover(), ledger=Ledger())
    stage = run_stage(loop, StageRequest("inv0", "invariant", _evidence(), dict(BASE_TREE)))
    assert stage.kept_base is True
    assert stage.fell_back is False
