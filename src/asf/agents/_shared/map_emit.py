"""Live map reporting for agent executions: start and end pulses.

Display-only: pulses go through the ambient tap (asf.models.map_tap)
with ``emit_safely``, so a broken or slow map can never change an
agent's result. Timestamps come from the agent's own runtime clock -
the same clock that stamps the execution's lifecycle events - never
from a wall clock read inside the agents package.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from asf.contracts.map_events import MapEvent, MapPhase, MapStatus, clean_label
from asf.contracts.models import AgentRequest, AgentResult
from asf.models.map_tap import default_map_tap, emit_safely

__all__ = ["emit_agent_result", "emit_agent_start"]


def _agent_event(
    request: AgentRequest,
    phase: MapPhase,
    status: MapStatus,
    ts: datetime,
) -> MapEvent | None:
    run_id = request.metadata.get("runId")
    if not isinstance(run_id, str) or not run_id:
        return None
    agent_id = request.agent_id or ""
    return MapEvent(
        id=f"{request.request_id}:agent:{phase}",
        ts=ts,
        run_id=run_id,
        span_id=request.request_id,
        type="agent",
        station="agents",
        phase=phase,
        status=status,
        label=clean_label(agent_id),
        task_id=request.task_id,
        project_id=request.project_id,
        agent_id=agent_id or None,
    )


def emit_agent_start(request: AgentRequest, ts: datetime) -> None:
    """Reports that an agent execution started, at the given time."""
    event = _agent_event(request, "start", "running", ts)
    if event is not None:
        emit_safely(default_map_tap(), event)


def emit_agent_result(request: AgentRequest, result: AgentResult, started_at: datetime) -> None:
    """Reports an execution's end from its result: status and first error."""
    duration = result.metrics.duration_seconds
    event = _agent_event(
        request, "end", _result_status(result), started_at + timedelta(seconds=duration)
    )
    if event is None:
        return
    error_code = result.errors[0].code if result.errors else None
    stamped = event.model_copy(
        update={"duration_ms": int(duration * 1000), "error_code": error_code}
    )
    emit_safely(default_map_tap(), stamped)


def _result_status(result: AgentResult) -> MapStatus:
    if result.status == "SUCCESS":
        return "ok"
    if result.status in ("REJECTED", "CANCELLED"):
        return "blocked"
    return "error"
