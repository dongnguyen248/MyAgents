"""The live map hub: bounded per-run pulse history for the dashboard.

One hub lives in the API process. Drive threads (agent taps) and the
engine's publisher append pulses; the map's SSE handler polls the
history with a cursor, so no asyncio object is ever touched from a
worker thread. History is memory-only: a run's pulses are dropped
once the run has been closed for a while, or when the run cap needs
the room. ``emit`` is O(1) and never raises - the map must not be
able to break a run.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from contextlib import suppress

from asf.contracts.map_events import MapEvent

__all__ = [
    "MapHub",
    "active_map_hub",
    "live_map_enabled",
    "set_active_map_hub",
]

MAX_EVENTS_PER_RUN = 1000
MAX_RUNS = 16
CLOSED_RUN_TTL_SECONDS = 600.0
ENV_LIVE_MAP = "ASF_LIVE_MAP"


class _Counters:
    """Cumulative totals for one run: unlike the bounded history
    these never drop entries, so dashboard totals stay true after
    the history evicts old pulses."""

    def __init__(self) -> None:
        self.station_totals: dict[str, int] = {}
        self.agent_totals: dict[str, int] = {}
        self.station_errors: dict[str, int] = {}
        self.used_tokens: int = 0
        self.used_calls: int = 0

    def count(self, event: MapEvent) -> None:
        """Fold one pulse into the cumulative counters."""
        if event.phase in ("start", "moment"):
            self.station_totals[event.station] = self.station_totals.get(event.station, 0) + 1
            if event.agent_id:
                self.agent_totals[event.agent_id] = self.agent_totals.get(event.agent_id, 0) + 1
        if event.phase == "end" and event.status in ("error", "blocked"):
            self.station_errors[event.station] = self.station_errors.get(event.station, 0) + 1
        if event.type == "model" and event.phase == "end":
            self.used_calls += 1
            self.used_tokens += (event.prompt_tokens or 0) + (event.completion_tokens or 0)


class _RunHistory:
    def __init__(self) -> None:
        self.events: deque[MapEvent] = deque(maxlen=MAX_EVENTS_PER_RUN)
        self.seen: int = 0
        self.closed_at: float | None = None
        self.last_seen: float = 0.0
        self.counters = _Counters()


class MapHub:
    """Thread-safe bounded store of map pulses, grouped by run."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runs: dict[str, _RunHistory] = {}
        self._limit_tokens: int | None = None
        self._limit_calls: int | None = None

    def set_budget_limits(self, limit_tokens: int | None, limit_calls: int | None) -> None:
        self._limit_tokens = limit_tokens
        self._limit_calls = limit_calls

    def emit(self, event: MapEvent) -> None:
        # The map must never break a run: any hub failure is swallowed.
        with suppress(Exception), self._lock:
            history = self._history_for(event.run_id)
            history.events.append(event)
            history.counters.count(event)
            history.seen += 1
            history.last_seen = time.monotonic()
            self._sweep_locked()

    def mark_closed(self, run_id: str) -> None:
        with self._lock:
            history = self._runs.get(run_id)
            if history is not None and history.closed_at is None:
                history.closed_at = time.monotonic()

    def snapshot(self, run_id: str, since: int = 0) -> tuple[list[MapEvent], int]:
        """Events for a run from cursor ``since``, plus the next cursor."""
        with self._lock:
            history = self._runs.get(run_id)
            if history is None:
                return [], 0
            events = list(history.events)
            seen = history.seen
        dropped = seen - len(events)
        start = max(0, since - dropped)
        return events[start:], seen

    def has_run(self, run_id: str) -> bool:
        with self._lock:
            return run_id in self._runs

    def budget(self, run_id: str) -> dict[str, int | None]:
        """Token/call usage from the run's cumulative counters."""
        with self._lock:
            history = self._runs.get(run_id)
            used_tokens = history.counters.used_tokens if history is not None else 0
            used_calls = history.counters.used_calls if history is not None else 0
        return {
            "usedTokens": used_tokens,
            "limitTokens": self._limit_tokens,
            "usedCalls": used_calls,
            "limitCalls": self._limit_calls,
        }

    def counters(self, run_id: str) -> dict[str, dict[str, int]]:
        """Cumulative per-station, per-agent and per-station-error totals."""
        with self._lock:
            history = self._runs.get(run_id)
            if history is None:
                return {"stations": {}, "agents": {}, "errors": {}}
            return {
                "stations": dict(history.counters.station_totals),
                "agents": dict(history.counters.agent_totals),
                "errors": dict(history.counters.station_errors),
            }

    def _history_for(self, run_id: str) -> _RunHistory:
        history = self._runs.get(run_id)
        if history is None:
            history = _RunHistory()
            self._runs[run_id] = history
        return history

    def _sweep_locked(self) -> None:
        now = time.monotonic()
        stale = [
            run_id
            for run_id, history in self._runs.items()
            if history.closed_at is not None and now - history.closed_at > CLOSED_RUN_TTL_SECONDS
        ]
        for run_id in stale:
            del self._runs[run_id]
        while len(self._runs) > MAX_RUNS:
            closed = [r for r, h in self._runs.items() if h.closed_at is not None]
            pool = closed if closed else list(self._runs)
            oldest = min(pool, key=lambda r: self._runs[r].last_seen)
            del self._runs[oldest]


_active_hub: MapHub | None = None


def set_active_map_hub(hub: MapHub | None) -> None:
    global _active_hub
    _active_hub = hub


def active_map_hub() -> MapHub | None:
    return _active_hub


def live_map_enabled() -> bool:
    """The ASF_LIVE_MAP switch: on unless explicitly set to 0/false/no."""
    raw = os.environ.get(ENV_LIVE_MAP, "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}
