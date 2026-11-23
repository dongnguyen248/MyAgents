"""The live map tap: sink protocol, ambient default, gateway wrapper.

The map is display-only. A tap's ``emit`` must be O(1), non-blocking
and never raise; ``emit_safely`` additionally swallows any tap error,
so a broken or slow map can never change a model call's outcome.
When no default tap is installed (tests, library use), reporting is
a no-op.

Attribution mirrors the counting gateway's tracker: BaseAgent opens
a ``map_call_context`` around each execution, and the gateway
wrapper reads it to stamp pulses with the run, task, agent and
request ids. Ids and timestamps derive from that context (the
request id, a per-execution call counter, the execution's start
time), never from a fresh id generator or wall clock, so reporting
consumes nothing the execution itself would notice.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta
from time import perf_counter
from typing import Any, Protocol

from asf.contracts.map_events import MapEvent, MapStatus, clean_label
from asf.contracts.models import AgentRequest, ModelRequest, ModelResponse
from asf.models.finish import classify_finish_reason
from asf.models.ports import ModelGateway

__all__ = [
    "MapTap",
    "MapTapGateway",
    "current_map_context",
    "default_map_tap",
    "emit_safely",
    "map_call_context",
    "set_default_map_tap",
]


class MapTap(Protocol):
    """Sink for live map pulses. Implementations must never block."""

    def emit(self, event: MapEvent) -> None: ...


_default_tap: MapTap | None = None


def set_default_map_tap(tap: MapTap | None) -> None:
    global _default_tap
    _default_tap = tap


def default_map_tap() -> MapTap | None:
    return _default_tap


def emit_safely(tap: MapTap | None, event: MapEvent) -> None:
    if tap is None:
        return
    # A map failure must never reach the caller.
    with suppress(Exception):
        tap.emit(event)


@dataclass
class MapCallContext:
    """Which execution the model calls in flight belong to."""

    run_id: str
    task_id: str | None
    agent_id: str
    request_id: str
    started_at: datetime
    calls: int = 0
    tool_calls: int = 0


_current: ContextVar[MapCallContext | None] = ContextVar("asf_map_context", default=None)


def current_map_context() -> MapCallContext | None:
    """The execution context tool wrappers attribute their pulses to."""
    return _current.get()


@contextmanager
def map_call_context(request: AgentRequest, started_at: datetime) -> Iterator[None]:
    """Marks the enclosed work as one agent execution for map pulses."""
    run_id = request.metadata.get("runId")
    if not isinstance(run_id, str) or not run_id or not request.agent_id:
        yield
        return
    ctx = MapCallContext(
        run_id=run_id,
        task_id=request.task_id,
        agent_id=request.agent_id,
        request_id=request.request_id,
        started_at=started_at,
    )
    token = _current.set(ctx)
    try:
        yield
    finally:
        _current.reset(token)


class MapTapGateway:
    """ModelGateway wrapper reporting one pulse pair per model call."""

    def __init__(self, inner: ModelGateway, tap: MapTap) -> None:
        self._inner = inner
        self._tap = tap

    def complete(self, request: ModelRequest) -> ModelResponse:
        ctx = _current.get()
        if ctx is None:
            return self._inner.complete(request)
        ctx.calls += 1
        span_id = f"{ctx.request_id}:model:{ctx.calls}"
        self._emit_start(request, ctx, span_id)
        started = perf_counter()
        try:
            response = self._inner.complete(request)
        except Exception as error:
            self._emit_error(ctx, span_id, started, error)
            raise
        self._emit_end(ctx, span_id, started, response)
        return response

    def _base(self, ctx: MapCallContext, span_id: str, suffix: str) -> dict[str, Any]:
        return {
            "id": f"{span_id}:{suffix}",
            "ts": ctx.started_at,
            "run_id": ctx.run_id,
            "span_id": span_id,
            "type": "model",
            "station": "model",
            "task_id": ctx.task_id,
            "agent_id": ctx.agent_id,
            "parent_id": ctx.request_id,
        }

    def _emit_start(self, request: ModelRequest, ctx: MapCallContext, span_id: str) -> None:
        model = request.model or _metadata_model(request)
        event = MapEvent(
            **self._base(ctx, span_id, "start"),
            phase="start",
            status="running",
            label=clean_label(model or "model"),
            model=model,
        )
        emit_safely(self._tap, event)

    def _emit_error(
        self, ctx: MapCallContext, span_id: str, started: float, error: Exception
    ) -> None:
        duration_ms = int((perf_counter() - started) * 1000)
        fields = self._base(ctx, span_id, "end")
        fields["ts"] = ctx.started_at + timedelta(milliseconds=duration_ms)
        event = MapEvent(
            **fields,
            phase="end",
            status="error",
            label=clean_label("model call failed"),
            duration_ms=duration_ms,
            error_code=getattr(error, "code", None) or type(error).__name__,
        )
        emit_safely(self._tap, event)

    def _emit_end(
        self, ctx: MapCallContext, span_id: str, started: float, response: ModelResponse
    ) -> None:
        kind = classify_finish_reason(response.finish_reason)
        if kind == "blocked":
            status: MapStatus = "blocked"
        elif kind == "truncated":
            status = "error"
        else:
            status = "ok"
        duration_ms = int((perf_counter() - started) * 1000)
        fields = self._base(ctx, span_id, "end")
        fields["ts"] = ctx.started_at + timedelta(milliseconds=duration_ms)
        event = MapEvent(
            **fields,
            phase="end",
            status=status,
            label=clean_label(response.model),
            model=response.model,
            duration_ms=duration_ms,
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
            error_code="LLM_OUTPUT_TRUNCATED" if kind == "truncated" else None,
        )
        emit_safely(self._tap, event)


def _metadata_model(request: ModelRequest) -> str | None:
    value = request.metadata.get("model")
    if isinstance(value, str) and value:
        return value
    return None
