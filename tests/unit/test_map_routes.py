from __future__ import annotations

import asyncio
import json
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


class StubResult:
    def __init__(self, output: Any) -> None:
        self.output = output


class StubRun:
    def __init__(self, run_id: str, results: list[StubResult]) -> None:
        self.id = run_id
        self.results = results


class StubService:
    def __init__(self, runs: list[StubRun] | None = None) -> None:
        self._stored = runs or []

    def get_workflow(self, run_id: str) -> dict[str, Any] | None:
        if run_id == "run-1":
            return {"status": "RUNNING"}
        return None

    def _runs(self) -> list[StubRun]:
        return list(self._stored)


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

    def snapshot_payload(self, service: StubService) -> dict[str, Any]:
        hub = MapHub()
        hub.emit(make_event("run-1", 1))
        set_active_map_hub(hub)
        app = register_map_routes(FastAPI(), service)
        client = TestClient(app)
        response = client.get("/map/snapshot", params={"runId": "run-1"})
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_snapshot_exposes_the_change_request_link(self) -> None:
        run = StubRun(
            "run-1",
            [
                StubResult({"hosting": "skipped"}),
                StubResult(
                    {
                        "changeRequest": {
                            "id": "42",
                            "url": "https://git.example.com/g/p/-/merge_requests/42",
                            "state": "opened",
                        },
                        "pipeline": {"status": "success"},
                    }
                ),
            ],
        )
        payload = self.snapshot_payload(StubService([run]))
        self.assertEqual(
            payload["hosting"],
            {"url": "https://git.example.com/g/p/-/merge_requests/42", "number": "42"},
        )

    def test_snapshot_strips_userinfo_query_and_fragment_from_the_url(self) -> None:
        dirty = (
            "https://oauth2:tok-userinfo-1@git.example.com:8443/g/p/-/merge_requests/42"
            "?access_token=tok-query-2#tok-fragment-3"
        )
        run = StubRun("run-1", [StubResult({"changeRequest": {"id": "42", "url": dirty}})])
        payload = self.snapshot_payload(StubService([run]))
        self.assertEqual(
            payload["hosting"],
            {"url": "https://git.example.com:8443/g/p/-/merge_requests/42", "number": "42"},
        )
        blob = json.dumps(payload)
        for secret in ("tok-userinfo-1", "tok-query-2", "tok-fragment-3", "oauth2"):
            self.assertNotIn(secret, blob)

    def test_snapshot_hides_hosting_without_metadata_or_with_a_bad_url(self) -> None:
        self.assertIsNone(self.snapshot_payload(StubService())["hosting"])
        odd = StubRun("run-1", [StubResult({"changeRequest": {"id": "7", "url": "ftp://x/7"}})])
        self.assertIsNone(self.snapshot_payload(StubService([odd]))["hosting"])
        no_id = StubRun("run-1", [StubResult({"changeRequest": {"url": "https://x/7"}})])
        self.assertIsNone(self.snapshot_payload(StubService([no_id]))["hosting"])

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


class MapTrackedTests(unittest.TestCase):
    def tearDown(self) -> None:
        set_active_map_hub(None)

    def _client(self, hub: MapHub) -> TestClient:
        set_active_map_hub(hub)
        app = register_map_routes(FastAPI(), StubService())
        return TestClient(app, raise_server_exceptions=False)

    def test_tracked_true_when_the_hub_has_the_run(self) -> None:
        hub = MapHub()
        hub.emit(make_event("run-1", 1))
        response = self._client(hub).get("/map/snapshot", params={"runId": "run-1"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["tracked"])
        self.assertEqual(len(payload["events"]), 1)

    def test_tracked_false_when_only_the_service_knows_the_run(self) -> None:
        response = self._client(MapHub()).get("/map/snapshot", params={"runId": "run-1"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["tracked"])
        self.assertEqual(payload["status"], "RUNNING")
        self.assertEqual(payload["events"], [])
        self.assertEqual(payload["counters"], {"stations": {}, "agents": {}, "errors": {}})

    def test_404_when_neither_the_hub_nor_the_service_knows_the_run(self) -> None:
        response = self._client(MapHub()).get("/map/snapshot", params={"runId": "ghost"})
        self.assertEqual(response.status_code, 404)
