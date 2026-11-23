from __future__ import annotations

import asyncio
import unittest
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from asf.api.map_routes import _stream, register_map_routes
from asf.api.service.map_hub import MapHub, set_active_map_hub
from asf.contracts.map_events import MapEvent

TS = datetime(2026, 11, 23, 9, 0, 0, tzinfo=UTC)


def make_event(run_id: str, number: int) -> MapEvent:
    return MapEvent(
        id=f"evt-{number}",
        ts=TS,
        run_id=run_id,
        span_id=f"span-{number}",
        type="agent",
        station="agents",
        phase="moment",
        status="ok",
        label="spec",
        agent_id="agent-spec",
    )


class StubService:
    def get_workflow(self, run_id: str) -> dict[str, Any] | None:
        if run_id == "run-1":
            return {"status": "RUNNING"}
        return None


class StubRequest:
    """A request that reports a disconnect after a set poll count."""

    def __init__(self, disconnect_after: int) -> None:
        self._disconnect_after = disconnect_after
        self.checks = 0

    async def is_disconnected(self) -> bool:
        self.checks += 1
        return self.checks > self._disconnect_after


class MapRoutesTests(unittest.TestCase):
    def tearDown(self) -> None:
        set_active_map_hub(None)

    def test_routes_absent_without_an_active_hub(self) -> None:
        set_active_map_hub(None)
        app = register_map_routes(FastAPI(), StubService())
        client = TestClient(app, raise_server_exceptions=False)
        self.assertEqual(client.get("/map/snapshot", params={"runId": "run-1"}).status_code, 404)

    def test_snapshot_carries_events_budget_and_counters(self) -> None:
        hub = MapHub()
        hub.emit(make_event("run-1", 1))
        set_active_map_hub(hub)
        app = register_map_routes(FastAPI(), StubService())
        client = TestClient(app)
        response = client.get("/map/snapshot", params={"runId": "run-1"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "RUNNING")
        self.assertEqual(len(payload["events"]), 1)
        self.assertEqual(payload["counters"]["stations"], {"agents": 1})
        self.assertEqual(payload["counters"]["agents"], {"agent-spec": 1})
        self.assertIn("budget", payload)

    def test_snapshot_unknown_run_is_404(self) -> None:
        set_active_map_hub(MapHub())
        app = register_map_routes(FastAPI(), StubService())
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/map/snapshot", params={"runId": "ghost"})
        self.assertEqual(response.status_code, 404)

    def test_stream_ends_when_the_client_disconnects(self) -> None:
        hub = MapHub()
        hub.emit(make_event("run-1", 1))
        request = StubRequest(disconnect_after=2)

        async def collect() -> list[str]:
            lines: list[str] = []
            async for chunk in _stream(StubService(), hub, "run-1", request):
                lines.append(chunk)
            return lines

        lines = asyncio.run(asyncio.wait_for(collect(), timeout=5))
        self.assertEqual(len(lines), 1)
        self.assertIn('"evt-1"', lines[0])
        self.assertGreaterEqual(request.checks, 3)


if __name__ == "__main__":
    unittest.main()
