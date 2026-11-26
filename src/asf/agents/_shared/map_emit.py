"""Live map reporting for agent executions: start, end, rejection pulses.

Display-only: pulses go through the ambient tap (asf.models.map_tap)
with ``emit_safely``, so a broken or slow map can never change an
agent's result. Start and end timestamps come from the agent's own
runtime clock - the same clock that stamps the execution's lifecycle
events - never from a wall clock read inside the agents package. A
rejection pulse is stamped from the ambient map call context (the
execution start plus the model time already spent), so it sorts after
the model call that produced the rejected output.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from asf.contracts.map_events import MapEvent, MapPhase, MapStatus, clean_label
from asf.contracts.models import AgentRequest, AgentResult
from asf.models.map_tap import current_map_context, default_map_tap, emit_safely

__all__ = [
    "TASK_STRUCTURE_REJECTED_LABEL",
    "emit_agent_result",
    "emit_agent_start",
    "emit_output_rejected",
    "sections_rejected_label",
]

INVALID_RESPONSE_CODE = "LLM_INVALID_RESPONSE"
TASK_STRUCTURE_REJECTED_LABEL = "rejected: invalid task structure"


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


def sections_rejected_label(missing: int, total: int, retrying: bool) -> str:
    """Counts-only rejection label; section names never reach the map."""
    suffix = ", retrying" if retrying else ""
    return f"rejected: missing {missing}/{total} sections{suffix}"


def emit_output_rejected(request: AgentRequest, label: str) -> None:
    """Reports one rejected model output as a moment pulse.

    Callers invoke this exactly once per rejection, at the point the
    output is judged unusable. Without an ambient map context (the
    execution is not being observed) nothing is emitted.
    """
    context = current_map_context()
    if context is None:
        return
    ts = context.started_at + timedelta(milliseconds=context.elapsed_ms)
    event = _agent_event(request, "moment", "error", ts)
    if event is None:
        return
    stamped = event.model_copy(
        update={
            "label": clean_label(label),
            "error_code": INVALID_RESPONSE_CODE,
            "attempt": context.calls or None,
        }
    )
    emit_safely(default_map_tap(), stamped)


def _result_status(result: AgentResult) -> MapStatus:
    if result.status == "SUCCESS":
        return "ok"
    if result.status in ("REJECTED", "CANCELLED"):
        return "blocked"
    return "error"
