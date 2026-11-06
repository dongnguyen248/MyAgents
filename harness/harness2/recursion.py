"""Parallel(k) / Sequential(k): the task-level recursion (H2 structure).

One Stage is one improver session: build an evidence bundle from
rollout trajectories, ask the improver for an edited harness tree,
validate it. A rejected edit is retried once with the validator's
message appended to the mission; a second rejection falls back to
the current harness (`fell_back`). An edit that changes nothing is
`kept_base`. A rollout that raises is recorded in the ledger as
dead and the run continues — rollouts are never raised.

In H2 the improver is scripted (see `demo.py`); the real
`GatewayImprover` is H3. Execution here is serial; concurrency
limits from config arrive with the real improver.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from harness.harness2.adapter import TaskAdapter
from harness.harness2.context import EvidenceBundle, EvidenceItem, build_evidence
from harness.harness2.ledger import Ledger
from harness.harness2.surface import Tree
from harness.harness2.trajectory import MIN_OBSERVATION_CHARS

__all__ = [
    "FinalCandidate",
    "ImproverPort",
    "Loop",
    "ModeResult",
    "StageRequest",
    "StageResult",
    "run_parallel",
    "run_sequential",
    "run_stage",
]

MAX_STAGE_ATTEMPTS = 2


class ImproverPort(Protocol):
    """Anything that can propose a harness edit from evidence."""

    def improve(self, mission: str, evidence: EvidenceBundle, harness: Tree) -> Tree:
        """Return a candidate tree (may equal `harness` for a no-op)."""
        ...


@dataclass(frozen=True)
class StageRequest:
    """One improver session's inputs: what to ask, from what evidence."""

    label: str
    mission: str
    evidence: EvidenceBundle
    base_tree: Tree


@dataclass
class Loop:
    """The collaborators every stage and rollout of a run shares."""

    adapter: TaskAdapter
    improver: ImproverPort
    ledger: Ledger


@dataclass(frozen=True)
class StageResult:
    label: str
    tree: Tree
    fell_back: bool = False
    kept_base: bool = False
    attempts: int = 1


@dataclass(frozen=True)
class FinalCandidate:
    label: str
    tree: Tree
    run_dir: Path
    delivered: bool
    dead: bool = False


@dataclass
class ModeResult:
    task_id: str
    mode: str
    k: int
    ledger: Ledger
    finals: list[FinalCandidate] = field(default_factory=list)
    stages: list[StageResult] = field(default_factory=list)


def run_stage(loop: Loop, request: StageRequest) -> StageResult:
    """One improver session with one validator-guided retry."""
    loop.ledger.record_session(request.label)
    mission = request.mission
    for attempt in range(1, MAX_STAGE_ATTEMPTS + 1):
        candidate = loop.improver.improve(mission, request.evidence, dict(request.base_tree))
        try:
            loop.adapter.validate_tree(candidate)
        except ValueError as error:
            if attempt < MAX_STAGE_ATTEMPTS:
                mission = (
                    f"{request.mission}\nThe validator rejected the previous attempt:\n{error}"
                )
                continue
            return StageResult(
                label=request.label,
                tree=dict(request.base_tree),
                fell_back=True,
                attempts=attempt,
            )
        kept = candidate == request.base_tree
        return StageResult(label=request.label, tree=candidate, kept_base=kept, attempts=attempt)
    raise AssertionError("unreachable: stage loop always returns")


def _rollout(loop: Loop, task_id: str, tree: Tree | None, label: str) -> Path | None:
    loop.ledger.record_rollout(label)
    try:
        return loop.adapter.execute(task_id, tree, run_id=f"{task_id}-{label}")
    except Exception:
        loop.ledger.record_dead_rollout(label)
        return None


def _evidence_items(
    adapter: TaskAdapter, runs: list[tuple[str, Path | None]]
) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    for label, run_dir in runs:
        if run_dir is None:
            items.append(
                EvidenceItem(label=label, trajectory="[ERROR] rollout died", delivered=False)
            )
            continue
        items.append(
            EvidenceItem(
                label=label,
                trajectory=adapter.trajectory(run_dir, obs_trunc=MIN_OBSERVATION_CHARS),
                delivered=adapter.delivered(run_dir),
            )
        )
    return items


def _final(loop: Loop, task_id: str, label: str, tree: Tree) -> FinalCandidate:
    run_dir = _rollout(loop, task_id, tree, label)
    delivered = run_dir is not None and loop.adapter.delivered(run_dir)
    fallback_dir = run_dir if run_dir is not None else Path(label)
    return FinalCandidate(
        label=label, tree=tree, run_dir=fallback_dir, delivered=delivered, dead=run_dir is None
    )


def run_parallel(
    adapter: TaskAdapter, task_id: str, *, k: int, improver: ImproverPort
) -> ModeResult:
    """Parallel(k): k base, k INV + k DOM probes, k compositions."""
    ledger = Ledger()
    loop = Loop(adapter=adapter, improver=improver, ledger=ledger)
    result = ModeResult(task_id=task_id, mode="parallel", k=k, ledger=ledger)
    base_tree = adapter.base_harness()
    base_runs = [(f"base{i}", _rollout(loop, task_id, None, f"base{i}")) for i in range(k)]
    evidence = build_evidence(task_id, _evidence_items(adapter, base_runs))
    probes: list[tuple[str, Path | None]] = list(base_runs)
    for prefix, mission in (("inv", "invariant"), ("dom", "domain")):
        for i in range(k):
            request = StageRequest(f"{prefix}{i}", mission, evidence, base_tree)
            stage = run_stage(loop, request)
            result.stages.append(stage)
            probes.append((f"{prefix}{i}", _rollout(loop, task_id, stage.tree, f"{prefix}{i}")))
    pool = build_evidence(task_id, _evidence_items(adapter, probes))
    for i in range(k):
        stage = run_stage(loop, StageRequest(f"agg{i}", "compose", pool, base_tree))
        result.stages.append(stage)
        result.finals.append(_final(loop, task_id, f"agg{i}", stage.tree))
    ledger.assert_identity(k)
    return result


def run_sequential(
    adapter: TaskAdapter, task_id: str, *, k: int, improver: ImproverPort
) -> ModeResult:
    """Sequential(k): k rounds of propose/probe/compose from a checkpoint."""
    ledger = Ledger()
    loop = Loop(adapter=adapter, improver=improver, ledger=ledger)
    result = ModeResult(task_id=task_id, mode="sequential", k=k, ledger=ledger)
    checkpoint = adapter.base_harness()
    runs: list[tuple[str, Path | None]] = [
        (f"base{i}", _rollout(loop, task_id, None, f"base{i}")) for i in range(k)
    ]
    for round_index in range(k):
        evidence = build_evidence(task_id, _evidence_items(adapter, runs))
        for prefix, mission in (("inv", "invariant"), ("dom", "domain")):
            label = f"{prefix}{round_index}"
            stage = run_stage(loop, StageRequest(label, mission, evidence, checkpoint))
            result.stages.append(stage)
            runs.append((label, _rollout(loop, task_id, stage.tree, label)))
        compose_label = f"c{round_index}"
        pool = build_evidence(task_id, _evidence_items(adapter, runs))
        stage = run_stage(loop, StageRequest(compose_label, "compose", pool, checkpoint))
        result.stages.append(stage)
        checkpoint = stage.tree
        final = _final(loop, task_id, compose_label, checkpoint)
        result.finals.append(final)
        runs.append((compose_label, None if final.dead else final.run_dir))
    ledger.assert_identity(k)
    return result
