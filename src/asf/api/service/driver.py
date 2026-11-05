"""FactoryService driver — the background drive, pool and retry scheduler.

``DriverMixin`` carries these methods of ``FactoryService`` (a pure
split of the former single service.py; no behavior change).
The facade in the package ``__init__`` combines the mixins.
Attribute and cross-group method declarations below describe
the state the facade's ``__init__`` establishes and the
sibling parts provide — declarations only, never assignments.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from asf.api.scheduler import RunScheduler
from asf.api.service import (
    _TERMINAL_STAGES,
    logger,
)
from asf.orchestrator.engine import Orchestrator
from asf.orchestrator.execution import WorkflowExecution
from asf.orchestrator.ports import ConcurrentModificationError


class DriverMixin:
    # ------------------------------------------------------------------
    # run control
    # ------------------------------------------------------------------
    # Ceiling on automatic step executions per drive. A full workflow
    # needs ~11 ticks plus bounded fix rounds — far below this; the cap
    # only guards against a pathological no-progress loop.
    _DRIVE_LIMIT = 100

    # Drives run on a bounded pool of background worker threads: a
    # step can sit in a model call for minutes, and driving on the
    # request thread froze the whole API — the dashboard could not
    # even load its lists until the call returned. The pool bound
    # (execution.maxConcurrentRuns) also bounds how many runs can be
    # inside model calls at once. The stores keep one connection per
    # thread, so request threads and drive threads never share a
    # connection object. Workers are daemon threads; shutdown()
    # stops them cleanly.
    _on_run_terminal: Callable[[str, str, str], None] | None
    _engine: Orchestrator
    _clock: Callable[[], datetime] | None
    _scheduler: RunScheduler
    _max_concurrent_runs: int
    _drive_condition: threading.Condition
    _drive_active: set[str]
    _drive_queue: deque[str]
    _drive_workers: list[threading.Thread]
    _drive_stopped: bool
    _advance_split_chain: Callable[[str], None]
    _apply_requested_cancel: Callable[[str], bool]
    _invalidate_runs_cache: Callable[[], None]
    _runs: Callable[[], list[WorkflowExecution]]
    _workflow_status: Callable[[WorkflowExecution], str]
    get_workflow: Callable[[str], dict[str, Any] | None]

    def _drive_in_background(self, run_id: str) -> None:
        """Queue a drive for a run (coalesced per run, pool-bounded)."""
        with self._drive_condition:
            if run_id in self._drive_active or self._drive_stopped:
                return
            self._drive_active.add(run_id)
            self._drive_queue.append(run_id)
            self._ensure_drive_workers_locked()
            self._drive_condition.notify_all()

    def _ensure_drive_workers_locked(self) -> None:
        while len(self._drive_workers) < self._max_concurrent_runs:
            worker = threading.Thread(
                target=self._drive_pool_loop,
                name=f"asf-drive-pool-{len(self._drive_workers)}",
                daemon=True,
            )
            self._drive_workers.append(worker)
            # Start under the lock, like the old per-run threads, so
            # no waiter can observe a worker that has not started.
            worker.start()

    def _drive_pool_loop(self) -> None:
        while True:
            with self._drive_condition:
                while not self._drive_queue and not self._drive_stopped:
                    self._drive_condition.wait()
                if not self._drive_queue:
                    return  # stopped and drained
                run_id = self._drive_queue.popleft()
            try:
                self._drive_worker(run_id)
            except Exception:
                # _drive_worker is expected to contain drive errors;
                # a worker must never die and shrink the pool silently.
                logger.exception(
                    "Drive worker failed unexpectedly for run %s",
                    run_id,
                )

    def _drive_worker(self, run_id: str) -> None:
        try:
            self._drive(run_id)
        finally:
            self._invalidate_runs_cache()
            with self._drive_condition:
                self._drive_active.discard(run_id)
                self._drive_condition.notify_all()
            # A cancel requested just as the drive parked (e.g. the run
            # reached an approval gate in the same moment) must not be
            # lost with the drive: nobody is dispatching now, so the
            # cancellation can be applied directly.
            self._apply_requested_cancel(run_id)
            # If this run was a split part that just completed, its
            # completion is what starts the next part.
            self._advance_split_chain(run_id)

    def _wait_for_drive(self, run_id: str, timeout: float | None = None) -> None:
        """Wait until no drive for ``run_id`` is queued or running."""
        with self._drive_condition:
            self._drive_condition.wait_for(
                lambda: run_id not in self._drive_active,
                timeout=timeout,
            )

    def wait_for_drives(self, timeout: float | None = None) -> None:
        """Block until every queued/running drive finishes."""
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._drive_condition:
            while self._drive_active:
                remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
                if remaining is not None and remaining <= 0:
                    return
                self._drive_condition.wait(timeout=remaining)

    def shutdown(self) -> None:
        """Stops the retry scheduler and the drive pool (clean exit)."""
        self.stop_scheduler()
        with self._drive_condition:
            self._drive_stopped = True
            self._drive_condition.notify_all()
            workers = list(self._drive_workers)
        for worker in workers:
            worker.join(timeout=5)

    def _flush_observations_quietly(self, run_id: str) -> None:
        # RuntimeError: nothing to deliver to. ValueError: another
        # thread is dispatching this run right now and the engine will
        # not flush mid-dispatch. At-least-once delivery; a later
        # flush retries.
        with suppress(RuntimeError, ValueError):
            self._engine.flush_observations(run_id)

    def _drive(self, run_id: str) -> None:
        """Advance a run automatically until it needs a human or stops.

        Ticks while the run is RUNNING and each tick makes progress, so a
        run flows on its own from one approval gate to the next — and
        through the code/test/fix steps in between — without anyone
        pressing a "next step" button. Stops at approval gates
        (WAITING_APPROVAL), terminal stages, scheduled retries (the tick
        makes no progress until the backoff is due) and escalations.
        Best-effort by design: a dispatch problem (e.g. an interrupted
        run awaiting recover()) stops the drive and leaves the run for
        manual handling instead of failing the request that triggered it.
        """
        for _ in range(self._DRIVE_LIMIT):
            if self._apply_requested_cancel(run_id):
                break
            run = self._engine.get(run_id)
            if self._workflow_status(run) != "RUNNING":
                break
            before = (run.state.stage, len(run.results))
            try:
                self._engine.tick(run_id)
            except ConcurrentModificationError:
                # Another writer owns this run now (a racing drive, a
                # manual tick, a second process). Losing the claim is
                # a normal outcome, not a run failure: stop this drive
                # and let the owner (or a later drive) carry the run.
                logger.warning(
                    "Drive for run %s stopped: the run was claimed by another writer",
                    run_id,
                )
                break
            except Exception:
                logger.exception(
                    "Drive for run %s stopped on an unexpected error",
                    run_id,
                )
                break
            if self._apply_requested_cancel(run_id):
                break
            # Publish the step's events (its STEP_STARTED line and the
            # agent's result events) now, not only when the whole drive
            # parks: SSE subscribers see the run's log grow step by step.
            self._flush_observations_quietly(run_id)
            after = self._engine.get(run_id)
            if (after.state.stage, len(after.results)) == before:
                break
        # ValueError: another thread is dispatching this run right
        # now (a manual tick racing the drive) and the engine will
        # not flush mid-dispatch. At-least-once delivery; retried on
        # a later flush.
        with suppress(RuntimeError, ValueError):
            self._engine.flush_observations(run_id)
        self._sync_retry_schedule(run_id)
        self._notify_run_terminal(run_id)

    def _notify_run_terminal(self, run_id: str) -> None:
        """Fires the assembly's terminal hook when the run is finished.

        Idempotent on the receiver's side: drives can observe the
        same terminal run more than once (e.g. a startup re-drive of
        an already finished run), and the hook must tolerate that.
        """
        if self._on_run_terminal is None:
            return
        try:
            run = self._engine.get(run_id)
        except Exception:
            return
        if run.state.stage not in _TERMINAL_STAGES:
            return
        try:
            self._on_run_terminal(run.id, run.project_id, run.state.stage)
        except Exception:
            logger.exception(
                "Terminal hook failed for run %s (stage %s)",
                run_id,
                run.state.stage,
            )

    def _scheduler_clock(self) -> datetime:
        """Clock for the retry scheduler: the service's injected
        clock, else the engine's, else (stub assemblies only) UTC now."""
        clock = self._clock or getattr(self._engine, "_clock", None)
        if clock is not None:
            return clock()
        return datetime.now(UTC)

    def _sync_retry_schedule(self, run_id: str) -> None:
        """Registers a parked run's retry_at with the scheduler.

        Called when a drive parks: if the run is waiting out a retry
        backoff, the scheduler will drive it again when the backoff
        expires — no manual tick needed. A run without a pending
        retry is unregistered (its schedule, if any, is stale).
        """
        try:
            run = self._engine.get(run_id)
        except Exception:
            return
        if run.retry_at is not None:
            self._scheduler.register(run_id, run.retry_at)
        else:
            self._scheduler.unregister(run_id)

    def stop_scheduler(self) -> None:
        """Stops the retry scheduler thread (tests/shutdown)."""
        self._scheduler.stop()

    def drive_run(self, run_id: str) -> dict[str, Any] | None:
        """Auto-advance a run to its next stopping point; returns its view."""
        self._wait_for_drive(run_id)
        self._drive(run_id)
        return self.get_workflow(run_id)

    def drive_active_runs(self) -> None:
        """Auto-advance every known mid-flight run (used at API startup).

        A run left at a work stage by a backend restart continues to its
        next approval gate on its own. A run left with ``in_flight`` set
        had its dispatch interrupted by the stop — at startup nothing
        can still be in flight, so the stale marker is recovered
        (the interrupted step replays) instead of stranding the run.
        """
        for run in self._runs():
            if run.in_flight is not None:
                try:
                    self._engine.recover(
                        run.id,
                        reason="API startup: the previous backend stopped mid-dispatch",
                        retry_interrupted=True,
                    )
                except Exception:
                    continue
                run = self._engine.get(run.id)
            if run.retry_at is not None:
                # Parked on a retry backoff when the backend stopped:
                # the scheduler drives it when the backoff expires
                # (a retry_at already in the past fires at once).
                self._scheduler.register(run.id, run.retry_at)
            if self._workflow_status(run) == "RUNNING":
                self._drive_in_background(run.id)
        # A split part that completed just before the previous backend
        # stopped may never have started its successor; the chain
        # state lives in the completed run's context, so re-checking
        # every completed split part here restarts any stalled chain.
        for run in self._runs():
            if run.state.stage == "COMPLETED":
                self._advance_split_chain(run.id)
