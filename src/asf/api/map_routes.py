"""Live map endpoints: GET /map/snapshot and GET /map/events (SSE).

Registered on the app by the demo assembly only when the live map is
enabled (ASF_LIVE_MAP); with no active hub the routes do not exist,
exactly like the map itself. Same posture as /events: the local API
has no auth layer, so these endpoints share that posture and serve
only the metadata a MapEvent carries - names and counts, never
content.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from asf.api.service.map_hub import MapHub, active_map_hub

__all__ = ["register_map_routes"]

_POLL_SECONDS = 0.25
_HEARTBEAT_POLLS = 60


def _run_status(service: Any, run_id: str) -> str | None:
    view = service.get_workflow(run_id)
    if view is None:
        return None
    status = view.get("status")
    return status if isinstance(status, str) else None


def _hosting_link(service: Any, run_id: str) -> dict[str, str] | None:
    """The run's change-request link from its stored step results.

    The public workflow view deliberately omits step outputs, so this
    reads the run record's results directly (same package, read-only).
    Only the URL and the PR/MR number are exposed - never the rest of
    the hosting output - and anything unexpected yields None, which
    the dashboard renders as "no link".
    """
    runs = getattr(service, "_runs", None)
    if not callable(runs):
        return None
    try:
        records = runs()
    except Exception:
        return None
    run = next((item for item in records if getattr(item, "id", None) == run_id), None)
    if run is None:
        return None
    link: dict[str, str] | None = None
    for result in getattr(run, "results", None) or []:
        link = _change_request_link(getattr(result, "output", None)) or link
    return link


def _change_request_link(output: Any) -> dict[str, str] | None:
    if not isinstance(output, Mapping):
        return None
    ref = output.get("changeRequest")
    if not isinstance(ref, Mapping):
        return None
    url, number = ref.get("url"), ref.get("id")
    if not isinstance(url, str) or not url.startswith(("https://", "http://")):
        return None
    if number is None or str(number) == "":
        return None
    return {"url": url, "number": str(number)}


def _snapshot_payload(service: Any, hub: MapHub, run_id: str) -> dict[str, Any] | None:
    status = _run_status(service, run_id)
    if status is None and not hub.has_run(run_id):
        return None
    events, _ = hub.snapshot(run_id)
    return {
        "runId": run_id,
        "status": status or "UNKNOWN",
        "budget": hub.budget(run_id),
        "counters": hub.counters(run_id),
        "hosting": _hosting_link(service, run_id),
        "events": [event.to_contract() for event in events],
    }


async def _stream(service: Any, hub: MapHub, run_id: str, request: Request) -> AsyncIterator[str]:
    events, cursor = hub.snapshot(run_id)
    for event in events:
        yield f"data: {json.dumps(event.to_contract())}\n\n"
    idle_polls = 0
    while True:
        if await request.is_disconnected():
            return
        fresh, cursor = hub.snapshot(run_id, since=cursor)
        for event in fresh:
            yield f"data: {json.dumps(event.to_contract())}\n\n"
        if fresh:
            idle_polls = 0
        else:
            idle_polls += 1
            if idle_polls >= _HEARTBEAT_POLLS:
                idle_polls = 0
                yield ": heartbeat\n\n"
        await asyncio.sleep(_POLL_SECONDS)


def register_map_routes(app: FastAPI, service: Any) -> FastAPI:
    """Adds the map endpoints when a hub is active; returns the app."""
    hub = active_map_hub()
    if hub is None:
        return app

    @app.get("/map/snapshot")
    async def map_snapshot(runId: str) -> Any:
        payload = _snapshot_payload(service, hub, runId)
        if payload is None:
            return JSONResponse(status_code=404, content={"detail": "Run not found"})
        return payload

    @app.get("/map/events")
    async def map_events(runId: str, request: Request) -> StreamingResponse:
        return StreamingResponse(
            _stream(service, hub, runId, request),
            media_type="text/event-stream",
        )

    return app
