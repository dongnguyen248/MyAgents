"""Parallel(k) / Sequential(k): the task-level recursion (H2 structure, H3 engine).

One Stage is one improver session: build an evidence bundle from
rollout trajectories, ask the improver for an edited harness tree,
validate it. A rejected edit — or an improver that raises — is
retried once with the rejection message fed back; a second failure
falls back to the current harness (`fell_back`). An edit that
changes nothing is `kept_base`. A rollout that raises is recorded
in the ledger as dead and the run continues — rollouts are never
raised.

Composition stages receive the candidate stages' notes as
`decisions` (what each session says it did, or how it ended), so
the composer merges claims against probe trajectories instead of
re-deriving them. Independent work inside a phase may run on a
bounded thread pool (`workers`); the default is serial, and phase
barriers keep the ledger identity exact either way. Wiring
`workers` to run configuration arrives with the runner (H4).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from harness.harness2.adapter import TaskAdapter
from harness.harness2.context import EvidenceBundle, EvidenceItem, build_evidence
from harness.harness2.improver import ImproverPort, ImproverReply, StageContext
from harness.harness2.ledger import Ledger
from harness.harness2.surface import Tree
from harness.harness2.trajectory import MIN_OBSERVATION_CHARS

__all__ = [
    "FinalCandidate",
    "Loop",
    "ModeOptions",
    "ModeResult",
    "StageRequest",
    "StageResult",
    "run_parallel",
    "run_sequential",
    "run_stage",
]

MAX_STAGE_ATTEMPTS = 2


@dataclass(frozen=True)
class ModeOptions:
    """One mode run's shape: the budget factor k and the phase pool size."""

    k: int
    workers: int = 1


@dataclass(frozen=True)
class StageRequest:
    """One improver session's inputs: what to ask, from what evidence."""

    label: str
    mission: str
    evidence: EvidenceBundle
    base_tree: Tree
    decisions: Mapping[str, str] | None = None


@dataclass
class Loop:
    """The collaborators every stage and rollout of a run shares."""

    adapter: TaskAdapter
    improver: ImproverPort
    ledger: Ledger
    workers: int = 1


@dataclass(frozen=True)
class StageResult:
    label: str
    tree: Tree
    fell_back: bool = False
    kept_base: bool = False
    attempts: int = 1
    notes: str = ""
    error: str = ""


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
    """One improver session with one rejection-guided retry."""
    loop.ledger.record_session(request.label)
    feedback = ""
    for attempt in range(1, MAX_STAGE_ATTEMPTS + 1):
        try:
            reply = _improve(loop, request, feedback)
            loop.adapter.validate_tree(reply.tree)
        except Exception as error:
            if attempt < MAX_STAGE_ATTEMPTS:
                feedback = f"The previous attempt was rejected:\n{error}"
                continue
            return StageResult(
                label=request.label,
                tree=dict(request.base_tree),
                fell_back=True,
                attempts=attempt,
                error=str(error),
            )
        kept = reply.tree == request.base_tree
        return StageResult(
            label=request.label,
            tree=reply.tree,
            kept_base=kept,
            attempts=attempt,
            notes=reply.notes,
        )
    raise AssertionError("unreachable: stage loop always returns")


def _improve(loop: Loop, request: StageRequest, feedback: str) -> ImproverReply:
    context = StageContext(decisions=request.decisions, feedback=feedback)
    return loop.improver.improve(
        request.mission, request.evidence, dict(request.base_tree), context
    )


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


def _decision_note(stage: StageResult) -> str:
    if stage.notes:
        return stage.notes
    if stage.fell_back:
        return f"fell back to the current harness ({stage.error})"
    if stage.kept_base:
        return "kept the current harness (no edit proposed)"
    return "edit adopted; the session left no notes"


def _decisions(stages: list[StageResult]) -> dict[str, str]:
    return {stage.label: _decision_note(stage) for stage in stages}


def _phase[T](workers: int, items: list[T], work: Callable[[T], object]) -> None:
    if workers <= 1 or len(items) <= 1:
        for item in items:
            work(item)
        return
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(work, items))


def _probe_candidates(
    loop: Loop,
    result: ModeResult,
    task_id: str,
    requests: list[StageRequest],
) -> tuple[list[StageResult], list[tuple[str, Path | None]]]:
    stages: list[StageResult | None] = [None] * len(requests)
    probes: list[tuple[str, Path | None] | None] = [None] * len(requests)

    def probe(index: int) -> None:
        request = requests[index]
        stage = run_stage(loop, request)
        stages[index] = stage
        probes[index] = (request.label, _rollout(loop, task_id, stage.tree, request.label))

    _phase(loop.workers, list(range(len(requests))), probe)
    ordered = [stage for stage in stages if stage is not None]
    result.stages.extend(ordered)
    return ordered, [run for run in probes if run is not None]


def run_parallel(
    adapter: TaskAdapter, task_id: str, *, improver: ImproverPort, options: ModeOptions
) -> ModeResult:
    """Parallel(k): k base, k INV + k DOM probes, k compositions."""
    k = options.k
    ledger = Ledger()
    loop = Loop(adapter=adapter, improver=improver, ledger=ledger, workers=options.workers)
    result = ModeResult(task_id=task_id, mode="parallel", k=k, ledger=ledger)
    base_tree = adapter.base_harness()
    base_runs = [(f"base{i}", _rollout(loop, task_id, None, f"base{i}")) for i in range(k)]
    evidence = build_evidence(task_id, _evidence_items(adapter, base_runs))
    probes: list[tuple[str, Path | None]] = list(base_runs)
    requests = [
        StageRequest(f"{prefix}{i}", mission, evidence, base_tree)
        for prefix, mission in (("inv", "invariant"), ("dom", "domain"))
        for i in range(k)
    ]
    candidates, candidate_runs = _probe_candidates(loop, result, task_id, requests)
    probes.extend(candidate_runs)
    pool = build_evidence(task_id, _evidence_items(adapter, probes))
    decisions = _decisions(candidates)
    for i in range(k):
        request = StageRequest(f"agg{i}", "aggregate", pool, base_tree, decisions)
        stage = run_stage(loop, request)
        result.stages.append(stage)
        result.finals.append(_final(loop, task_id, f"agg{i}", stage.tree))
    ledger.assert_identity(k)
    return result


def run_sequential(
    adapter: TaskAdapter, task_id: str, *, improver: ImproverPort, options: ModeOptions
) -> ModeResult:
    """Sequential(k): k rounds of propose/probe/compose from a checkpoint."""
    k = options.k
    ledger = Ledger()
    loop = Loop(adapter=adapter, improver=improver, ledger=ledger, workers=options.workers)
    result = ModeResult(task_id=task_id, mode="sequential", k=k, ledger=ledger)
    checkpoint = adapter.base_harness()
    runs: list[tuple[str, Path | None]] = [
        (f"base{i}", _rollout(loop, task_id, None, f"base{i}")) for i in range(k)
    ]
    for round_index in range(k):
        evidence = build_evidence(task_id, _evidence_items(adapter, runs))
        requests = [
            StageRequest(f"{prefix}{round_index}", mission, evidence, checkpoint)
            for prefix, mission in (("inv", "invariant"), ("dom", "domain"))
        ]
        candidates, candidate_runs = _probe_candidates(loop, result, task_id, requests)
        runs.extend(candidate_runs)
        pool = build_evidence(task_id, _evidence_items(adapter, runs))
        label = f"c{round_index}"
        request = StageRequest(label, "compose_round", pool, checkpoint, _decisions(candidates))
        stage = run_stage(loop, request)
        result.stages.append(stage)
        checkpoint = stage.tree
        final = _final(loop, task_id, label, checkpoint)
        result.finals.append(final)
        runs.append((label, None if final.dead else final.run_dir))
    ledger.assert_identity(k)
    return result
