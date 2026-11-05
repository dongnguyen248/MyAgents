"""Platform-side model usage accounting and step deadlines.

Agents never count their own tokens: :class:`CountingGateway`
wraps whatever gateway an agent was assembled with and accumulates
calls + token usage into a per-execution tracker that
``BaseAgent.execute`` opens via :func:`track_model_calls`. The
tracker lives in a context variable, so concurrent executions of
the same agent instance (the service drives runs in parallel
threads) each accumulate into their own tracker.

The same wrapper carries the step deadline: when the tracker was
opened with a step timeout, each call gets
``metadata["deadlineSeconds"]`` — the time REMAINING in the step
at the moment of the call — injected into a copy of the request,
so gateways can cap their HTTP timeout at
``min(configured, remaining)`` instead of only being checked
after the agent finishes.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime

from asf.contracts.models import ModelRequest, ModelResponse
from asf.models.ports import ModelGateway

__all__ = ["CountingGateway", "ModelCallTracker", "track_model_calls"]


@dataclass
class ModelCallTracker:
    """Usage accumulated for one agent execution."""

    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    _deadline_seconds: float | None = field(default=None, repr=False)
    _started_at: datetime | None = field(default=None, repr=False)
    _clock: Callable[[], datetime] | None = field(default=None, repr=False)

    def remaining_seconds(self) -> float | None:
        if (
            self._deadline_seconds is None
            or self._started_at is None
            or self._clock is None
        ):
            return None
        elapsed = (self._clock() - self._started_at).total_seconds()
        return self._deadline_seconds - elapsed


_current: ContextVar[ModelCallTracker | None] = ContextVar(
    "asf_model_call_tracker", default=None,
)


@contextmanager
def track_model_calls(
    *,
    timeout_seconds: float | None,
    clock: Callable[[], datetime],
    started_at: datetime | None = None,
) -> Iterator[ModelCallTracker]:
    """Opens the usage tracker for one agent execution.

    ``started_at`` lets the caller hand in the execution's own
    start stamp (BaseAgent already read the clock for it) so
    tracking costs no extra clock reads; it is only consulted when
    a deadline must be measured.
    """
    tracker = ModelCallTracker(
        _deadline_seconds=timeout_seconds,
        _started_at=(
            started_at
            if started_at is not None
            else (clock() if timeout_seconds is not None else None)
        ),
        _clock=clock if timeout_seconds is not None else None,
    )
    token = _current.set(tracker)
    try:
        yield tracker
    finally:
        _current.reset(token)


class CountingGateway:
    """ModelGateway wrapper: counts usage, injects step deadlines."""

    def __init__(self, inner: ModelGateway) -> None:
        self._inner = inner
        self._lock = threading.Lock()
        self.total_calls = 0
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0

    def complete(self, request: ModelRequest) -> ModelResponse:
        tracker = _current.get()
        outgoing = request
        if tracker is not None:
            remaining = tracker.remaining_seconds()
            if remaining is not None:
                outgoing = request.model_copy(update={
                    "metadata": {
                        **request.metadata,
                        # A floor keeps an expired deadline from
                        # becoming a zero/negative HTTP timeout; the
                        # gateway will simply time out immediately.
                        "deadlineSeconds": max(remaining, 0.05),
                    },
                })
        response = self._inner.complete(outgoing)
        with self._lock:
            self.total_calls += 1
            self.total_prompt_tokens += response.usage.prompt_tokens
            self.total_completion_tokens += response.usage.completion_tokens
        if tracker is not None:
            tracker.calls += 1
            tracker.prompt_tokens += response.usage.prompt_tokens
            tracker.completion_tokens += response.usage.completion_tokens
        return response
