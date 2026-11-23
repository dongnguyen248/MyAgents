"""Step and gate pulses for the live map, translated from engine events.

The engine already publishes an ActivityEvent for every step start,
approval decision, AI review and workflow outcome. This wrapper sits
on that publisher (in the demo assembly the metrics object doubles
as it), translates the events that carry a run id into map pulses,
and forwards everything to the wrapped publisher untouched. Agent
and model pulses come from the agent-side tap instead; the two
streams merge in the hub.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from contextlib import suppress
from typing import Any

from asf.api.service.map_hub import MapHub, active_map_hub, set_active_map_hub
from asf.contracts.map_events import MapEvent, MapStatus, clean_label
from asf.contracts.models import ActivityEvent
from asf.models.map_tap import set_default_map_tap

__all__ = ["MapPublisher", "install_live_map", "wrap_live_map_publisher"]

_TERMINAL = {"WORKFLOW_COMPLETED", "WORKFLOW_FAILED", "WORKFLOW_CANCELLED"}


def _pulse(event: ActivityEvent, run_id: str, **fields: Any) -> MapEvent:
    return MapEvent(
        id=uuid.uuid4().hex,
        ts=event.timestamp,
        run_id=run_id,
        span_id=event.id,
        label=clean_label(event.message or event.event_type),
        task_id=event.task_id,
        project_id=event.project_id,
        **fields,
    )


def _step_pulse(event: ActivityEvent, run_id: str) -> MapEvent:
    step_id = event.metadata.get("stepId")
    return _pulse(
        event,
        run_id,
        type="step",
        station="agents",
        phase="moment",
        status="running",
        step_id=step_id if isinstance(step_id, str) else None,
    )


def _review_pulse(event: ActivityEvent, run_id: str) -> MapEvent:
    return _pulse(event, run_id, type="gate", station="gates", phase="moment", status="running")


def _decision_pulse(event: ActivityEvent, run_id: str) -> MapEvent:
    status: MapStatus = "error" if "reject" in event.message.lower() else "ok"
    return _pulse(event, run_id, type="gate", station="gates", phase="moment", status=status)


def _escalation_pulse(event: ActivityEvent, run_id: str) -> MapEvent:
    return _pulse(event, run_id, type="gate", station="gates", phase="moment", status="blocked")


def _terminal_pulse(event: ActivityEvent, run_id: str) -> MapEvent:
    return _pulse(
        event, run_id, type="run", station="core", phase="moment", status=_terminal_status(event)
    )


def _terminal_status(event: ActivityEvent) -> MapStatus:
    if event.event_type == "WORKFLOW_COMPLETED":
        return "ok"
    if event.event_type == "WORKFLOW_FAILED":
        return "error"
    return "blocked"


_BUILDERS: dict[str, Callable[[ActivityEvent, str], MapEvent]] = {
    "STEP_STARTED": _step_pulse,
    "AI_REVIEW_STARTED": _review_pulse,
    "APPROVAL_DECIDED": _decision_pulse,
    "WORKFLOW_ESCALATED": _escalation_pulse,
    "WORKFLOW_COMPLETED": _terminal_pulse,
    "WORKFLOW_FAILED": _terminal_pulse,
    "WORKFLOW_CANCELLED": _terminal_pulse,
}


def _translate(event: ActivityEvent, hub: MapHub) -> None:
    run_id = event.metadata.get("runId")
    if not isinstance(run_id, str) or not run_id:
        return
    builder = _BUILDERS.get(event.event_type)
    if builder is None:
        return
    hub.emit(builder(event, run_id))
    if event.event_type in _TERMINAL:
        hub.mark_closed(run_id)


class MapPublisher:
    """EventPublisher wrapper: translates, then forwards untouched."""

    def __init__(self, inner: Any, hub: MapHub) -> None:
        self._inner = inner
        self._hub = hub

    def publish(self, event: ActivityEvent) -> None:
        # The map must never break event delivery.
        with suppress(Exception):
            _translate(event, self._hub)
        publish = getattr(self._inner, "publish", None)
        if publish is not None:
            publish(event)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def install_live_map(budget: Any) -> MapHub:
    """Creates the hub and installs it as the agents' default tap.

    Called from the demo assembly BEFORE the agent registry is built:
    agents pick the tap up when they wrap their model gateway, so the
    hub must already be the default by then.
    """
    hub = MapHub()
    limit_tokens = _sum_limits(budget.max_prompt_tokens, budget.max_completion_tokens)
    hub.set_budget_limits(limit_tokens, budget.max_model_calls)
    set_active_map_hub(hub)
    set_default_map_tap(hub)
    return hub


def _sum_limits(prompt: int | None, completion: int | None) -> int | None:
    parts = [value for value in (prompt, completion) if value is not None]
    if not parts:
        return None
    return sum(parts)


def wrap_live_map_publisher(inner: Any) -> Any:
    """Wraps the demo's publisher with the translator, when enabled."""
    hub = active_map_hub()
    if hub is None or inner is None:
        return inner
    return MapPublisher(inner, hub)
