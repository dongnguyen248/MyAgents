"""Orchestrator claim/execute/commit phases and optimistic locking.

These tests pin the concurrency contract against an in-memory
ExecutionStore that implements the same contract as the MariaDB
store (deep copies in/out, transactions serialize writers, saves
guarded by the run version): a dispatch never holds a store
transaction while its agent runs, a run can be claimed by only one
dispatcher, and a writer holding a stale copy of a run fails with
ConcurrentModificationError instead of overwriting a concurrent save.

The MariaDB-specific halves of the contract (the version column,
SELECT ... FOR UPDATE claims, lock waits) are covered against a real
server in tests/integration/test_mariadb_store.py.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager

import pytest

from asf.approval.models import ApprovalPolicy
from asf.contracts.models import Artifact
from asf.orchestrator import Orchestrator
from asf.orchestrator.execution import WorkflowExecution
from asf.orchestrator.ports import ConcurrentModificationError
from asf.state_machine.machine import InvalidTransition, RunState
from asf.storage.memory import InMemoryApprovalRepository
from tests.unit.test_orchestrator import NOW, make_engine


class InMemoryExecutionStore:
    """In-memory ExecutionStore with the MariaDB store's contract."""

    def __init__(self) -> None:
        self._runs: dict[str, WorkflowExecution] = {}
        self._lock = threading.RLock()
        self.approvals = InMemoryApprovalRepository()

    @contextmanager
    def transaction(self):  # noqa: ANN202 - test double
        with self._lock:
            yield

    def create_execution(self, run: WorkflowExecution) -> None:
        with self._lock:
            run.version = 0
            self._runs[run.id] = run.snapshot()

    def save_execution(self, run: WorkflowExecution) -> None:
        with self._lock:
            stored = self._runs.get(run.id)
            if stored is None:
                raise KeyError(run.id)
            if stored.version != run.version:
                raise ConcurrentModificationError(
                    f"Execution '{run.id}' was modified concurrently"
                    f" (expected version {run.version})",
                )
            run.version += 1
            self._runs[run.id] = run.snapshot()

    def get_execution(
        self,
        run_id: str,
        *,
        for_update: bool = False,
    ) -> WorkflowExecution:
        with self._lock:
            stored = self._runs.get(run_id)
            if stored is None:
                raise KeyError(run_id)
            return stored.snapshot()

    def list_executions(self, project_id: str) -> list[WorkflowExecution]:
        with self._lock:
            return [run.snapshot() for run in self._runs.values() if run.project_id == project_id]


def stored_engine(
    *,
    two_steps: bool = True,
    approval: bool = False,
) -> tuple[Orchestrator, object, object, InMemoryExecutionStore]:
    original, spec, plan, _ = make_engine(approval=approval, two_steps=two_steps)
    store = InMemoryExecutionStore()
    engine = Orchestrator(
        original._definition,
        original._registry,
        clock=original._clock,
        new_id=original._new_id,
        store=store,
        approval_policy=ApprovalPolicy(reviewers=["reviewer"]),
    )
    return engine, spec, plan, store


def start(engine: Orchestrator, task_id: str = "task-1") -> WorkflowExecution:
    return engine.start(
        task_id=task_id,
        project_id="project-1",
        inputs={"spec": {"requirement": "Add a feature"}},
        context={"project": {"name": "example"}},
    )


def produce_for(task_id: str, agent_name: str = "spec"):
    artifact = Artifact(
        id=f"art-{task_id}-{agent_name}",
        type=agent_name.upper(),
        name=agent_name,
        version="1",
        content={"text": agent_name},
        created_by=f"agent-{agent_name}",
        created_at=NOW,
    )
    return {"summary": "done"}, [artifact]


# ---------------------------------------------------------------------------
# No transaction is held while the agent executes
# ---------------------------------------------------------------------------


class DepthTrackingStore:
    """ExecutionStore wrapper counting open transactions."""

    def __init__(self, inner: InMemoryExecutionStore) -> None:
        self._inner = inner
        self.depth = 0
        self.max_depth = 0

    @property
    def approvals(self):  # noqa: ANN202 - delegates to the inner store
        return self._inner.approvals

    @contextmanager
    def transaction(self):  # noqa: ANN202 - context manager passthrough
        self.depth += 1
        self.max_depth = max(self.max_depth, self.depth)
        try:
            with self._inner.transaction():
                yield
        finally:
            self.depth -= 1

    def create_execution(self, run: WorkflowExecution) -> None:
        self._inner.create_execution(run)

    def save_execution(self, run: WorkflowExecution) -> None:
        self._inner.save_execution(run)

    def get_execution(
        self,
        run_id: str,
        *,
        for_update: bool = False,
    ) -> WorkflowExecution:
        return self._inner.get_execution(run_id, for_update=for_update)

    def list_executions(self, project_id: str) -> list[WorkflowExecution]:
        return self._inner.list_executions(project_id)


def test_agent_executes_outside_any_store_transaction():
    original, spec, _, _ = make_engine()
    store = DepthTrackingStore(InMemoryExecutionStore())
    engine = Orchestrator(
        original._definition,
        original._registry,
        clock=original._clock,
        new_id=original._new_id,
        store=store,
        approval_policy=ApprovalPolicy(reviewers=["reviewer"]),
    )
    depths_during_execute: list[int] = []

    def spying_produce(request):
        depths_during_execute.append(store.depth)
        return produce_for(request.task_id)

    spec._run_behavior = spying_produce
    run = engine.tick(start(engine).id)

    assert run.artifacts.get("SPEC") is not None
    assert depths_during_execute == [0]  # the acceptance criterion
    assert store.max_depth >= 1  # claim/commit really used transactions
    assert store.depth == 0


def test_decide_on_another_run_is_not_blocked_by_a_running_agent():
    engine, spec, _, store = stored_engine(approval=True)
    parked = engine.tick(start(engine, "task-parked").id)
    assert parked.approval_id is not None

    entered = threading.Event()

    def slow_produce(request):
        entered.set()
        time.sleep(2)
        return produce_for(request.task_id)

    spec._run_behavior = slow_produce
    slow_run = start(engine, "task-slow")
    errors: list[BaseException] = []

    def dispatch() -> None:
        try:
            engine.tick(slow_run.id)
        except BaseException as error:  # noqa: B036 - asserted below
            errors.append(error)

    thread = threading.Thread(target=dispatch)
    thread.start()
    try:
        assert entered.wait(timeout=5), "agent never started"
        began = time.monotonic()
        decided = engine.decide(parked.id, reviewer="reviewer", decision="APPROVED")
        elapsed = time.monotonic() - began
        assert elapsed < 0.5, f"decide() blocked for {elapsed:.2f}s"
        assert decided.approval_id is None
        assert decided.state.stage == "PLAN"  # the gate was passed
    finally:
        thread.join(timeout=10)
    assert not thread.is_alive()
    assert errors == []
    assert engine.get(slow_run.id).artifacts.get("SPEC") is not None


# ---------------------------------------------------------------------------
# A run can be claimed only once
# ---------------------------------------------------------------------------


def _tick_collecting(engine: Orchestrator, run_id: str, outcomes: list, barrier) -> None:
    barrier.wait(timeout=5)
    try:
        outcomes.append(("ok", engine.tick(run_id)))
    except BaseException as error:  # noqa: B036 - asserted by the caller
        outcomes.append(("error", error))


def _assert_single_dispatch(outcomes: list, calls: list[str]) -> None:
    assert calls == ["task-1"]  # the agent ran exactly once
    kinds = sorted(kind for kind, _ in outcomes)
    assert kinds == ["error", "ok"]
    error = next(value for kind, value in outcomes if kind == "error")
    # The loser is refused clearly: the in-process guard, the claimed
    # in_flight token, or — if it arrived after the winner committed —
    # the terminal-stage transition check.
    assert isinstance(
        error,
        (ValueError, ConcurrentModificationError, InvalidTransition),
    )


def test_two_threads_tick_one_run_dispatches_once():
    engine, spec, _, _store = stored_engine(two_steps=False)
    calls: list[str] = []

    def counting_produce(request):
        calls.append(request.task_id)
        time.sleep(1)
        return produce_for(request.task_id)

    spec._run_behavior = counting_produce
    run = start(engine)
    barrier = threading.Barrier(2)
    outcomes: list = []
    threads = [
        threading.Thread(
            target=_tick_collecting,
            args=(engine, run.id, outcomes, barrier),
        )
        for _ in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    _assert_single_dispatch(outcomes, calls)


def test_two_engines_sharing_a_store_cannot_claim_the_same_run():
    engine, spec, _, store = stored_engine(two_steps=False)
    other = Orchestrator(
        engine._definition,
        engine._registry,
        clock=engine._clock,
        new_id=engine._new_id,
        store=store,
        approval_policy=ApprovalPolicy(reviewers=["reviewer"]),
    )
    calls: list[str] = []

    def counting_produce(request):
        calls.append(request.task_id)
        time.sleep(1)
        return produce_for(request.task_id)

    spec._run_behavior = counting_produce
    run = start(engine)
    barrier = threading.Barrier(2)
    outcomes: list = []
    threads = [
        threading.Thread(
            target=_tick_collecting,
            args=(engine, run.id, outcomes, barrier),
        ),
        threading.Thread(
            target=_tick_collecting,
            args=(other, run.id, outcomes, barrier),
        ),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    _assert_single_dispatch(outcomes, calls)


# ---------------------------------------------------------------------------
# Optimistic locking at the store contract
# ---------------------------------------------------------------------------


def test_stale_version_save_raises_concurrent_modification():
    engine, _, _, store = stored_engine()
    run = start(engine)
    first = store.get_execution(run.id)
    second = store.get_execution(run.id)
    assert first.version == second.version == 0

    first.context["writer"] = "first"
    store.save_execution(first)
    assert first.version == 1

    second.context["writer"] = "second"
    with pytest.raises(ConcurrentModificationError):
        store.save_execution(second)
    assert second.version == 0  # the failed save did not bump the copy

    saved = store.get_execution(run.id)
    assert saved.version == 1
    assert saved.context["writer"] == "first"  # no lost update


def test_save_of_unknown_run_still_raises_key_error():
    store = InMemoryExecutionStore()
    ghost = WorkflowExecution(
        id="missing",
        task_id="t",
        project_id="p",
        state=RunState(stage="SPEC", revisions={}),
        started_at=NOW,
        updated_at=NOW,
    )
    with pytest.raises(KeyError):
        store.save_execution(ghost)


# ---------------------------------------------------------------------------
# Agent failure does not strand the run
# ---------------------------------------------------------------------------


def test_agent_exception_fails_the_run_and_clears_in_flight():
    engine, spec, _, store = stored_engine()

    def boom(request):
        raise RuntimeError("agent blew up")

    spec._run_behavior = boom
    run = engine.tick(start(engine).id)
    assert run.state.stage == "FAILED"
    assert run.in_flight is None

    saved = store.get_execution(run.id)
    assert saved.in_flight is None
    # Terminal, not stuck: the next tick refuses as a completed-state
    # transition, not as an interrupted dispatch needing recover().
    with pytest.raises(InvalidTransition):
        engine.tick(run.id)
