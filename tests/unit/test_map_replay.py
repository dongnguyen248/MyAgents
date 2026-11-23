from __future__ import annotations

import os
import stat
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from asf.api.map_routes import register_map_routes
from asf.api.service.map_hub import MapHub, set_active_map_hub
from asf.api.service.map_replay import MapReplayStore, set_active_replay_store, valid_run_id
from asf.contracts.map_events import MapEvent
from asf.contracts.models import AgentRequest, ModelRequest, ModelResponse, ModelUsage
from asf.models.map_tap import MapTapGateway, map_call_context

TS = datetime(2026, 11, 23, 9, 0, 0, tzinfo=UTC)


def make_event(run_id: str, number: int, **overrides: Any) -> MapEvent:
    fields: dict[str, Any] = {
        "id": f"evt-{number}",
        "ts": TS + timedelta(seconds=number),
        "run_id": run_id,
        "span_id": f"span-{number}",
        "type": "model",
        "station": "model",
        "phase": "moment",
        "status": "ok",
        "label": "fake-1",
        "agent_id": "agent-spec",
    }
    fields.update(overrides)
    return MapEvent(**fields)


def closing_event(run_id: str) -> MapEvent:
    return make_event(
        run_id, 999, type="run", station="core", phase="moment", label="completed", agent_id=None
    )


def close_run(hub: MapHub, run_id: str) -> None:
    hub.emit(closing_event(run_id))
    hub.mark_closed(run_id)


class ReplyGateway:
    def complete(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(
            content="a spec draft",
            model="fake-1",
            usage=ModelUsage(prompt_tokens=120, completion_tokens=30),
            finish_reason="stop",
        )


class MapReplayStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name) / "map-runs"
        self.hub = MapHub()
        self.store = MapReplayStore(self.directory, self.hub)
        self.store.start()
        self.hub.set_sink(self.store.observe)
        self.hub.set_close_sink(self.store.close_run)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def emit_run(self, run_id: str, count: int) -> None:
        for number in range(1, count + 1):
            self.hub.emit(make_event(run_id, number))
        close_run(self.hub, run_id)
        self.store.flush()

    def test_events_and_footer_are_written(self) -> None:
        self.emit_run("run-1", 3)
        path = self.directory / "run-1.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 5)
        payload = self.store.read_replay("run-1")
        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertTrue(payload["complete"])
        self.assertFalse(payload["truncated"])
        self.assertEqual(len(payload["events"]), 4)
        self.assertEqual(payload["counters"], self.hub.counters("run-1"))
        self.assertEqual(payload["budget"], self.hub.budget("run-1"))

    def test_event_cap_still_writes_the_footer_with_true_totals(self) -> None:
        capped = MapReplayStore(self.directory, self.hub, max_events=5)
        capped.start()
        self.hub.set_sink(capped.observe)
        self.hub.set_close_sink(capped.close_run)
        for number in range(1, 9):
            self.hub.emit(make_event("run-1", number))
        close_run(self.hub, "run-1")
        capped.flush()
        payload = capped.read_replay("run-1")
        assert payload is not None
        self.assertEqual(len(payload["events"]), 5)
        self.assertTrue(payload["truncated"])
        self.assertEqual(payload["counters"], self.hub.counters("run-1"))
        self.assertEqual(payload["counters"]["stations"], {"model": 8, "core": 1})

    def test_byte_cap_truncates_but_the_footer_lands(self) -> None:
        capped = MapReplayStore(self.directory, self.hub, max_bytes=300)
        capped.start()
        self.hub.set_sink(capped.observe)
        self.hub.set_close_sink(capped.close_run)
        for number in range(1, 7):
            self.hub.emit(make_event("run-1", number))
        close_run(self.hub, "run-1")
        capped.flush()
        payload = capped.read_replay("run-1")
        assert payload is not None
        self.assertTrue(payload["complete"])
        self.assertTrue(payload["truncated"])
        self.assertLess(len(payload["events"]), 6)

    def test_a_run_without_a_closing_pulse_is_incomplete(self) -> None:
        self.hub.emit(make_event("run-1", 1))
        self.store.flush()
        payload = self.store.read_replay("run-1")
        assert payload is not None
        self.assertFalse(payload["complete"])
        self.assertIsNone(payload["counters"])
        summaries = self.store.list_replays()
        self.assertEqual(len(summaries), 1)
        self.assertFalse(summaries[0]["complete"])

    def test_listing_and_reading_survive_a_fresh_store(self) -> None:
        self.emit_run("run-1", 2)
        fresh = MapReplayStore(self.directory, MapHub())
        summaries = fresh.list_replays()
        self.assertEqual([item["runId"] for item in summaries], ["run-1"])
        self.assertTrue(summaries[0]["complete"])
        self.assertIsNotNone(fresh.read_replay("run-1"))

    def test_sweep_drops_old_files_and_runs_beyond_the_newest_50(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        old = self.directory / "run-old.jsonl"
        old.write_text("{}\n", encoding="utf-8")
        past = (datetime.now(UTC) - timedelta(days=8)).timestamp()
        os.utime(old, (past, past))
        for index in range(55):
            (self.directory / f"run-{index:02d}.jsonl").write_text("{}\n", encoding="utf-8")
        self.store.sweep()
        remaining = list(self.directory.glob("*.jsonl"))
        self.assertEqual(len(remaining), 50)
        self.assertNotIn(old, remaining)

    def test_files_are_owner_only(self) -> None:
        self.emit_run("run-1", 1)
        mode = stat.S_IMODE((self.directory / "run-1.jsonl").stat().st_mode)
        self.assertEqual(mode, 0o600)

    def test_run_id_validation_blocks_traversal(self) -> None:
        for bad in ("../secret", "a/b", "a\\b", "..", "", ".hidden", "a b"):
            self.assertFalse(valid_run_id(bad), bad)
            self.assertIsNone(self.store.read_replay(bad))
        self.assertTrue(valid_run_id("run-1_a"))

    def test_a_broken_directory_disables_the_writer_and_agents_are_unaffected(self) -> None:
        blocker = Path(self.tmp.name) / "blocker"
        blocker.write_text("not a directory", encoding="utf-8")
        broken = MapReplayStore(blocker, self.hub)
        broken.start()
        self.hub.set_sink(broken.observe)
        request = AgentRequest(
            request_id="req-1",
            task_id="task-1",
            project_id="proj-1",
            workflow_id="software-development",
            agent_id="agent-spec",
            input={},
            metadata={"runId": "run-1"},
        )
        gateway = MapTapGateway(ReplyGateway(), self.hub)
        outgoing = ModelRequest(messages=[{"role": "user", "content": "hi"}])
        with map_call_context(request, TS):
            reply = gateway.complete(outgoing)
        self.assertEqual(reply.content, "a spec draft")
        self.assertEqual(self.hub.counters("run-1")["stations"], {"model": 1})


class MapReplayRouteTests(unittest.TestCase):
    def tearDown(self) -> None:
        set_active_map_hub(None)
        set_active_replay_store(None)

    def test_routes_serve_the_listing_and_one_replay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            hub = MapHub()
            store = MapReplayStore(Path(tmp) / "map-runs", hub)
            store.start()
            hub.set_sink(store.observe)
            hub.set_close_sink(store.close_run)
            hub.emit(make_event("run-1", 1))
            close_run(hub, "run-1")
            store.flush()
            set_active_map_hub(hub)
            set_active_replay_store(store)
            client = TestClient(register_map_routes(FastAPI(), object()))
            listing = client.get("/map/replays")
            self.assertEqual(listing.status_code, 200)
            self.assertEqual(listing.json()["replays"][0]["runId"], "run-1")
            replay = client.get("/map/replay", params={"runId": "run-1"})
            self.assertEqual(replay.status_code, 200)
            self.assertTrue(replay.json()["complete"])
            traversal = client.get("/map/replay", params={"runId": "../../etc/passwd"})
            self.assertEqual(traversal.status_code, 404)

    def test_replay_routes_are_absent_without_a_store(self) -> None:
        set_active_map_hub(MapHub())
        set_active_replay_store(None)
        client = TestClient(register_map_routes(FastAPI(), object()), raise_server_exceptions=False)
        self.assertEqual(client.get("/map/replays").status_code, 404)
        self.assertEqual(client.get("/map/replay", params={"runId": "run-1"}).status_code, 404)


if __name__ == "__main__":
    unittest.main()
