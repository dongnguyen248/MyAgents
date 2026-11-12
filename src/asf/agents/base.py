from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from asf.agents._shared.log_context import log_context
from asf.agents._shared.security import redact_text
from asf.contracts.models import (
    ActivityEvent,
    AgentMetadata,
    AgentRequest,
    AgentResult,
    Artifact,
    PlatformError,
    RunMetrics,
    ValidationResult,
)
from asf.models.counting import CountingGateway, ModelCallTracker, track_model_calls
from asf.models.errors import ModelGatewayError
from asf.models.ports import ModelGateway

logger = logging.getLogger(__name__)

__all__ = ["AgentErrorOptions", "AgentExecutionError", "AgentRuntime", "BaseAgent", "Issue"]


@dataclass(frozen=True)
class AgentErrorOptions:
    category: str = "INTEGRATION"
    retryable: bool = True
    details: dict[str, Any] | None = None
    status: Literal["FAILED", "REJECTED"] = "FAILED"


class AgentExecutionError(Exception):
    """Expected agent/port failure with a safe, explicit platform error."""

    def __init__(self, code: str, message: str, options: AgentErrorOptions | None = None) -> None:
        super().__init__(message)
        resolved = options or AgentErrorOptions()
        self.code = code
        self.message = message
        self.category = resolved.category
        self.retryable = resolved.retryable
        self.details = dict(resolved.details or {})
        self.status = resolved.status

    def to_platform_error(self, now: datetime) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "category": self.category,
            "retryable": self.retryable,
            "details": self.details,
            "timestamp": now,
        }


@dataclass(frozen=True)
class Issue:
    """Validation issue found in an AgentRequest."""

    path: str
    message: str


@dataclass(frozen=True)
class AgentRuntime:
    """Injected runtime dependencies for agents."""

    models: ModelGateway
    clock: Callable[[], datetime]
    new_id: Callable[[], str]

    def __post_init__(self) -> None:
        raw_clock = self.clock

        def _safe_clock() -> datetime:
            dt = raw_clock()
            if not isinstance(dt, datetime):
                raise TypeError("Clock must return a datetime instance")
            if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
                raise ValueError("Clock must return a timezone-aware datetime")
            return dt

        object.__setattr__(self, "clock", _safe_clock)


@dataclass(frozen=True)
class _Execution:
    request: AgentRequest
    tracker: ModelCallTracker
    t_start: datetime


@dataclass(frozen=True)
class _EventSpec:
    event_type: str
    message: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class _LifecycleContext:
    request: AgentRequest
    t_start: datetime
    t_end: datetime
    outcome: str
    artifacts: list[Artifact]
    error: PlatformError | None = None


def _make_event(
    agent: BaseAgent, request: AgentRequest, timestamp: datetime, spec: _EventSpec
) -> ActivityEvent:
    return ActivityEvent(
        id=agent._runtime.new_id(),
        timestamp=timestamp,
        project_id=request.project_id,
        task_id=request.task_id,
        workflow_id=request.workflow_id,
        agent_id=agent.metadata.id,
        event_type=spec.event_type,
        message=spec.message,
        metadata=spec.metadata,
    )


def _lifecycle_events(agent: BaseAgent, ctx: _LifecycleContext) -> list[ActivityEvent]:
    """The execution's activity trail, built in exactly one place.

    Always AGENT_STARTED (at t_start), then one ARTIFACT_CREATED per
    produced artifact (at t_end, only on the completed path — error
    results carry no artifacts), then the terminal event:
    AGENT_COMPLETED for outcome "COMPLETED", AGENT_FAILED for
    "FAILED", AGENT_REJECTED for "REJECTED". A failure/rejection
    event carries the error's code, category, retryable flag and a
    redacted, truncated message, so an operator reading the run's
    history sees WHY it failed without opening the result. Event ids
    are minted in that order.
    """
    request = ctx.request
    started = _EventSpec(
        "AGENT_STARTED", "Agent execution started", {"requestId": request.request_id}
    )
    events = [_make_event(agent, request, ctx.t_start, started)]
    if ctx.outcome == "COMPLETED":
        events.extend(_completion_events(agent, ctx))
    else:
        events.append(_failure_event(agent, ctx))
    return events


def _completion_events(agent: BaseAgent, ctx: _LifecycleContext) -> list[ActivityEvent]:
    request = ctx.request
    events: list[ActivityEvent] = []
    for artifact in ctx.artifacts:
        spec = _EventSpec(
            "ARTIFACT_CREATED",
            f"Artifact '{artifact.id}' created",
            {"requestId": request.request_id, "artifactId": artifact.id},
        )
        events.append(_make_event(agent, request, ctx.t_end, spec))
    completed = _EventSpec(
        "AGENT_COMPLETED", "Agent execution completed", {"requestId": request.request_id}
    )
    events.append(_make_event(agent, request, ctx.t_end, completed))
    return events


def _failure_event(agent: BaseAgent, ctx: _LifecycleContext) -> ActivityEvent:
    request = ctx.request
    metadata: dict[str, Any] = {"requestId": request.request_id}
    if ctx.error is not None:
        metadata.update(
            {
                "errorCode": ctx.error.code,
                "errorCategory": ctx.error.category,
                "retryable": ctx.error.retryable,
                "errorMessage": redact_text(ctx.error.message)[:300],
            }
        )
    rejected = ctx.outcome == "REJECTED"
    spec = _EventSpec(
        "AGENT_REJECTED" if rejected else "AGENT_FAILED",
        "Agent execution rejected" if rejected else "Agent execution failed",
        metadata,
    )
    return _make_event(agent, request, ctx.t_end, spec)


def _metrics(agent: BaseAgent, execution: _Execution, t_end: datetime) -> RunMetrics:
    duration = max(0.0, (t_end - execution.t_start).total_seconds())
    return agent._compute_metrics(execution.request, duration, execution.tracker)


def _log_failure(
    agent: BaseAgent,
    request: AgentRequest,
    error: ModelGatewayError | AgentExecutionError,
) -> None:
    # One console line per failed execution: the dashboard banner
    # shows only the headline message, so the recorded details (the
    # actual rejection cause) must reach the backend terminal to be
    # diagnosable at all.
    logger.warning(
        "agent %s failed: task=%s request=%s code=%s message=%s details=%s",
        agent.metadata.id,
        request.task_id,
        request.request_id,
        error.code,
        error.message,
        json.dumps(error.details, default=str)[:600] if error.details else "-",
    )


def _rejected_result(agent: BaseAgent, execution: _Execution, issues: list[Issue]) -> AgentResult:
    request = execution.request
    t_end = agent._runtime.clock()
    errors = [
        PlatformError(
            code="VALIDATION_FAILED",
            message=issue.message,
            category="VALIDATION",
            details={"path": issue.path},
            retryable=False,
            timestamp=t_end,
        )
        for issue in issues
    ]
    return AgentResult(
        request_id=request.request_id,
        agent_id=agent.metadata.id,
        status="REJECTED",
        output=None,
        artifacts=[],
        events=[],
        metrics=_metrics(agent, execution, t_end),
        errors=errors,
    )


def _success_result(
    agent: BaseAgent,
    execution: _Execution,
    output: Any,
    artifacts: list[Artifact],
) -> AgentResult:
    request = execution.request
    t_end = agent._runtime.clock()
    stamped = [artifact.model_copy(update={"created_at": t_end}) for artifact in artifacts]
    ctx = _LifecycleContext(request, execution.t_start, t_end, "COMPLETED", stamped)
    return AgentResult(
        request_id=request.request_id,
        agent_id=agent.metadata.id,
        status="SUCCESS",
        output=output,
        artifacts=stamped,
        events=_lifecycle_events(agent, ctx),
        metrics=_metrics(agent, execution, t_end),
        errors=[],
    )


def _known_error_result(
    agent: BaseAgent,
    execution: _Execution,
    error: ModelGatewayError | AgentExecutionError,
) -> AgentResult:
    request = execution.request
    t_end = agent._runtime.clock()
    _log_failure(agent, request, error)
    platform_error = PlatformError.model_validate(error.to_platform_error(t_end))
    rejected = isinstance(error, AgentExecutionError) and error.status == "REJECTED"
    if rejected:
        events: list[ActivityEvent] = []
    else:
        ctx = _LifecycleContext(
            request, execution.t_start, t_end, "FAILED", [], error=platform_error
        )
        events = _lifecycle_events(agent, ctx)
    status = error.status if isinstance(error, AgentExecutionError) else "FAILED"
    return AgentResult(
        request_id=request.request_id,
        agent_id=agent.metadata.id,
        status=status,
        output=None,
        artifacts=[],
        events=events,
        metrics=_metrics(agent, execution, t_end),
        errors=[platform_error],
    )


def _unexpected_error_result(
    agent: BaseAgent, execution: _Execution, exc: Exception
) -> AgentResult:
    request = execution.request
    t_end = agent._runtime.clock()
    platform_error = PlatformError(
        code="AGENT_EXECUTION_FAILED",
        message="Agent execution failed",
        category="AGENT",
        details={"exceptionType": type(exc).__name__},
        retryable=True,
        timestamp=t_end,
    )
    ctx = _LifecycleContext(request, execution.t_start, t_end, "FAILED", [], error=platform_error)
    return AgentResult(
        request_id=request.request_id,
        agent_id=agent.metadata.id,
        status="FAILED",
        output=None,
        artifacts=[],
        events=_lifecycle_events(agent, ctx),
        metrics=_metrics(agent, execution, t_end),
        errors=[platform_error],
    )


class BaseAgent(ABC):
    """Abstract base agent implementing the Agent port."""

    def __init__(self, runtime: AgentRuntime) -> None:
        # Every agent's gateway is wrapped once in the counting
        # gateway: usage accounting and step-deadline injection are
        # platform concerns, never the agent's own bookkeeping.
        if not isinstance(runtime.models, CountingGateway):
            runtime = AgentRuntime(
                models=CountingGateway(runtime.models),
                clock=runtime.clock,
                new_id=runtime.new_id,
            )
        self._runtime = runtime

    @property
    @abstractmethod
    def metadata(self) -> AgentMetadata:
        """Returns the static metadata of this agent."""
        ...

    @abstractmethod
    def _check(self, request: AgentRequest) -> list[Issue]:
        """Validates the request. Pure function, must not raise for bad input."""
        ...

    @abstractmethod
    def _run(self, request: AgentRequest) -> tuple[Any, list[Artifact]]:
        """Executes the agent logic. Returns (output, artifacts)."""
        ...

    def _compute_revision_count(self, request: AgentRequest) -> int:
        """Subclass hook to compute revision count. Default 0."""
        return 0

    def _compute_metrics(
        self,
        request: AgentRequest,
        duration_seconds: float,
        tracker: ModelCallTracker | None = None,
    ) -> RunMetrics:
        raw_attempt = request.metadata.get("attempt")
        if isinstance(raw_attempt, int) and not isinstance(raw_attempt, bool) and raw_attempt >= 1:
            attempt = raw_attempt
        else:
            attempt = 1

        revision_count = self._compute_revision_count(request)
        return RunMetrics(
            duration_seconds=duration_seconds,
            revision_count=revision_count,
            attempt=attempt,
            prompt_tokens=tracker.prompt_tokens if tracker is not None else 0,
            completion_tokens=(tracker.completion_tokens if tracker is not None else 0),
            model_calls=tracker.calls if tracker is not None else 0,
        )

    def get_metadata(self) -> AgentMetadata:
        """Returns agent metadata with status IDLE."""
        return self.metadata

    def validate(self, request: AgentRequest) -> ValidationResult:
        """Validates an AgentRequest without raising exceptions."""
        issues = self._check(request)
        if not issues:
            return ValidationResult(valid=True, errors=[])

        t = self._runtime.clock()
        errors = [
            PlatformError(
                code="VALIDATION_FAILED",
                message=issue.message,
                category="VALIDATION",
                details={"path": issue.path},
                retryable=False,
                timestamp=t,
            )
            for issue in issues
        ]
        return ValidationResult(valid=False, errors=errors)

    def execute(self, request: AgentRequest) -> AgentResult:
        """Executes the agent workflow according to platform rules.

        The whole execution runs inside a model-call tracker: usage
        lands in the result metrics without agents counting anything
        themselves, and the step timeout the orchestrator stamped
        into the request metadata becomes a live deadline the
        counting gateway forwards to the real gateway per call.
        It also runs inside the log context, so every line emitted
        while it executes carries the run/task/agent/request ids.
        """
        t_start = self._runtime.clock()
        raw_timeout = request.metadata.get("stepTimeoutSeconds")
        timeout = (
            float(raw_timeout)
            if isinstance(raw_timeout, (int, float))
            and not isinstance(raw_timeout, bool)
            and raw_timeout > 0
            else None
        )
        with (
            track_model_calls(
                timeout_seconds=timeout,
                clock=self._runtime.clock,
                started_at=t_start,
            ) as tracker,
            log_context(
                run_id=request.metadata.get("runId"),
                task=request.task_id,
                agent=request.agent_id,
                request_id=request.request_id,
            ),
        ):
            return self._execute_tracked(request, tracker, t_start)

    def _execute_tracked(
        self,
        request: AgentRequest,
        tracker: ModelCallTracker,
        t_start: datetime,
    ) -> AgentResult:
        execution = _Execution(request=request, tracker=tracker, t_start=t_start)
        issues = self._check(request)
        if issues:
            return _rejected_result(self, execution, issues)
        try:
            output, artifacts = self._run(request)
            return _success_result(self, execution, output, artifacts)
        except (ModelGatewayError, AgentExecutionError) as err:
            return _known_error_result(self, execution, err)
        except Exception as exc:
            return _unexpected_error_result(self, execution, exc)
