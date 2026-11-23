from __future__ import annotations

import time
import unittest
from datetime import UTC, datetime

from asf.api.service.map_hub import MAX_EVENTS_PER_RUN, MAX_RUNS, MapHub
from asf.contracts.map_events import MapEvent

TS = datetime(2026, 11, 23, 9, 0, 0, tzinfo=UTC)


def make_event(run_id: str, number: int, **overrides: object) -> MapEvent:
    fields: dict[str, object] = {
        "id": f"evt-{run_id}-{number}",
        "ts": TS,
        "run_id": run_id,
        "span_id": f"span-{number}",
        "type": "model",
        "station": "model",
        "phase": "end",
        "status": "ok",
        "label": "fake-model",
        "prompt_tokens": 10,
        "completion_tokens": 5,
    }
    fields.update(overrides)
    return MapEvent.model_validate(fields)


class MapHubTests(unittest.TestCase):
    def test_snapshot_returns_events_in_order_with_cursor(self) -> None:
        hub = MapHub()
        hub.emit(make_event("run-1", 1))
        hub.emit(make_event("run-1", 2))
        events, cursor = hub.snapshot("run-1")
        self.assertEqual([e.id for e in events], ["evt-run-1-1", "evt-run-1-2"])
        self.assertEqual(cursor, 2)
        fresh, cursor = hub.snapshot("run-1", since=cursor)
        self.assertEqual(fresh, [])
        hub.emit(make_event("run-1", 3))
        fresh, cursor = hub.snapshot("run-1", since=cursor)
        self.assertEqual([e.id for e in fresh], ["evt-run-1-3"])
        self.assertEqual(cursor, 3)

    def test_unknown_run_snapshots_empty(self) -> None:
        hub = MapHub()
        self.assertEqual(hub.snapshot("nope"), ([], 0))
        self.assertFalse(hub.has_run("nope"))

    def test_history_is_bounded_per_run(self) -> None:
        hub = MapHub()
        for number in range(MAX_EVENTS_PER_RUN + 50):
            hub.emit(make_event("run-1", number))
        events, cursor = hub.snapshot("run-1")
        self.assertEqual(len(events), MAX_EVENTS_PER_RUN)
        self.assertEqual(cursor, MAX_EVENTS_PER_RUN + 50)
        self.assertEqual(events[0].id, "evt-run-1-50")

    def test_runs_are_capped_oldest_first(self) -> None:
        hub = MapHub()
        for number in range(MAX_RUNS + 2):
            hub.emit(make_event(f"run-{number}", 1))
        self.assertFalse(hub.has_run("run-0"))
        self.assertTrue(hub.has_run(f"run-{MAX_RUNS + 1}"))

    def test_closed_run_is_swept_after_the_ttl(self) -> None:
        hub = MapHub()
        hub.emit(make_event("run-old", 1))
        hub.mark_closed("run-old")
        history = hub._runs["run-old"]
        history.closed_at = time.monotonic() - 10_000
        hub.emit(make_event("run-new", 1))
        self.assertFalse(hub.has_run("run-old"))
        self.assertTrue(hub.has_run("run-new"))

    def test_budget_sums_model_pulses_and_reports_limits(self) -> None:
        hub = MapHub()
        hub.set_budget_limits(1000, 10)
        hub.emit(make_event("run-1", 1))
        hub.emit(make_event("run-1", 2))
        hub.emit(make_event("run-1", 3, type="agent", station="agents"))
        budget = hub.budget("run-1")
        self.assertEqual(budget["usedTokens"], 30)
        self.assertEqual(budget["usedCalls"], 2)
        self.assertEqual(budget["limitTokens"], 1000)
        self.assertEqual(budget["limitCalls"], 10)

    def test_emit_never_raises_on_a_full_hub(self) -> None:
        hub = MapHub()
        for number in range(MAX_RUNS * 2):
            hub.emit(make_event(f"run-{number}", 1))
        hub.emit(make_event("run-final", 1))
        self.assertTrue(hub.has_run("run-final"))

    def test_counters_survive_history_eviction(self) -> None:
        hub = MapHub()
        total = MAX_EVENTS_PER_RUN + 50
        for number in range(total):
            hub.emit(make_event("run-1", number, phase="start", status="running"))
            hub.emit(make_event("run-1", number))
        events, _ = hub.snapshot("run-1")
        self.assertEqual(len(events), MAX_EVENTS_PER_RUN)
        counters = hub.counters("run-1")
        self.assertEqual(counters["stations"], {"model": total})
        budget = hub.budget("run-1")
        self.assertEqual(budget["usedCalls"], total)
        self.assertEqual(budget["usedTokens"], total * 15)

    def test_counters_track_agents_and_errors(self) -> None:
        hub = MapHub()
        hub.emit(make_event("run-1", 1, phase="start", status="running", agent_id="agent-test"))
        hub.emit(make_event("run-1", 2, status="error", agent_id="agent-test"))
        hub.emit(make_event("run-1", 3, type="agent", station="agents", phase="moment"))
        counters = hub.counters("run-1")
        self.assertEqual(counters["stations"], {"model": 1, "agents": 1})
        self.assertEqual(counters["agents"], {"agent-test": 1})
        self.assertEqual(counters["errors"], {"model": 1})

    def test_counters_for_unknown_run_are_empty(self) -> None:
        hub = MapHub()
        self.assertEqual(hub.counters("nope"), {"stations": {}, "agents": {}, "errors": {}})
        self.assertEqual(hub.budget("nope")["usedTokens"], 0)


if __name__ == "__main__":
    unittest.main()
