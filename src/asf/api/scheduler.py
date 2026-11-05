"""Wakes runs when their scheduled retry comes due.

The orchestrator parks a failed step by stamping ``retry_at`` on the
run; nothing in the engine polls for it. Before this scheduler, a
parked run only moved again if someone ticked it by hand (or the
backend restarted and ``drive_active_runs`` picked it up) — retries
were scheduled and then stranded. The scheduler keeps a heap of
(run_id, retry_at), sleeps until the earliest entry is due *by the
injected clock*, and asks the service to drive that run. Driving is
the only thing it does: the drive still has to win the run's claim,
and losing that race is a normal outcome handled by the drive itself.
"""

from __future__ import annotations

import heapq
import itertools
import logging
import threading
from collections.abc import Callable
from datetime import datetime

logger = logging.getLogger("asf.api.scheduler")

# Upper bound on one wait: even with a frozen (test) clock the loop
# re-checks periodically, and a notify() makes any wait return at
# once, so this only bounds how stale the wait can get.
_MAX_WAIT_SECONDS = 5.0


class RunScheduler:
    """Single background thread that fires due retry wake-ups."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        wake: Callable[[str], None],
        periodic: Callable[[], None] | None = None,
        periodic_seconds: float = 30,
    ) -> None:
        self._clock = clock
        self._wake = wake
        # Optional housekeeping invoked every ``periodic_seconds``
        # (by the injected clock) whether or not any retry is due —
        # the service uses it to re-adopt orphaned runs.
        self._periodic = periodic
        self._periodic_seconds = periodic_seconds
        self._last_periodic: datetime | None = None
        self._condition = threading.Condition()
        self._heap: list[tuple[datetime, int, str]] = []
        self._registrations: dict[str, tuple[datetime, int]] = {}
        self._sequence = itertools.count()
        self._thread: threading.Thread | None = None
        self._stopped = False

    # -- registration -------------------------------------------------

    def register(self, run_id: str, retry_at: datetime) -> None:
        """Schedules (or reschedules) ``run_id`` for ``retry_at``."""
        with self._condition:
            sequence = next(self._sequence)
            self._registrations[run_id] = (retry_at, sequence)
            heapq.heappush(self._heap, (retry_at, sequence, run_id))
            self._condition.notify_all()
        self.start()

    def unregister(self, run_id: str) -> None:
        with self._condition:
            self._registrations.pop(run_id, None)
            self._condition.notify_all()

    def registered(self) -> dict[str, datetime]:
        """Current registrations (tests/diagnostics)."""
        with self._condition:
            return {run_id: retry_at for run_id, (retry_at, _seq) in self._registrations.items()}

    # -- lifecycle ----------------------------------------------------

    def start(self) -> None:
        """Starts the scheduler thread if not already running."""
        with self._condition:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stopped = False
            self._thread = threading.Thread(
                target=self._run,
                name="asf-run-scheduler",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        """Stops the thread and joins it; safe to call repeatedly."""
        with self._condition:
            self._stopped = True
            self._condition.notify_all()
            thread = self._thread
        if thread is not None:
            thread.join(timeout=5)
        with self._condition:
            if self._thread is thread:
                self._thread = None

    def notify(self) -> None:
        """Wakes the loop to recompute due times (clock moved)."""
        with self._condition:
            self._condition.notify_all()

    # -- loop -----------------------------------------------------------

    def _run(self) -> None:
        while True:
            due: list[str] = []
            run_periodic = False
            with self._condition:
                if self._stopped:
                    return
                now = self._clock()
                if self._periodic is not None and (
                    self._last_periodic is None
                    or (now - self._last_periodic).total_seconds() >= self._periodic_seconds
                ):
                    self._last_periodic = now
                    run_periodic = True
                while self._heap and self._heap[0][0] <= now:
                    retry_at, sequence, run_id = heapq.heappop(self._heap)
                    current = self._registrations.get(run_id)
                    if current != (retry_at, sequence):
                        continue  # superseded registration; drop stale entry
                    del self._registrations[run_id]
                    due.append(run_id)
                if not due:
                    wait = _MAX_WAIT_SECONDS
                    if self._heap:
                        remaining = (self._heap[0][0] - now).total_seconds()
                        wait = max(0.0, min(wait, remaining))
                    self._condition.wait(timeout=wait)
            if run_periodic and self._periodic is not None:
                try:
                    self._periodic()
                except Exception:
                    logger.exception("Periodic scheduler callback failed")
            # Wake outside the lock: driving a run can take minutes and
            # must not block registrations.
            for run_id in due:
                try:
                    self._wake(run_id)
                except Exception:
                    logger.exception(
                        "Scheduled wake-up for run %s failed",
                        run_id,
                    )
