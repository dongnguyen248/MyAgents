from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

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

__all__ = ["AgentRuntime", "BaseAgent", "Issue", "AgentExecutionError"]


class AgentExecutionError(Exception):
    """Expected agent/port failure with a safe, explicit platform error."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        category: str = "INTEGRATION",
        retryable: bool = True,
        details: dict[str, Any] | None = None,
        status: Literal["FAILED", "REJECTED"] = "FAILED",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.category = category
        self.retryable = retryable
        self.details = dict(details or {})
        self.status = status

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
        with track_model_calls(
            timeout_seconds=timeout,
            clock=self._runtime.clock,
            started_at=t_start,
        ) as tracker:
            return self._execute_tracked(request, tracker, t_start)

    def _lifecycle_events(
        self,
        request: AgentRequest,
        t_start: datetime,
        t_end: datetime,
        outcome: str,
        artifacts: list[Artifact],
    ) -> list[ActivityEvent]:
        """The execution's activity trail, built in exactly one place.

        Always AGENT_STARTED (at t_start), then one ARTIFACT_CREATED
        per produced artifact (at t_end, only on the completed path —
        error results carry no artifacts), then the terminal event:
        AGENT_COMPLETED for outcome "COMPLETED", AGENT_FAILED for
        "FAILED". Event ids are minted in that order.
        """

        def event(
            timestamp: datetime,
            event_type: str,
            message: str,
            metadata: dict[str, Any],
        ) -> ActivityEvent:
            return ActivityEvent(
                id=self._runtime.new_id(),
                timestamp=timestamp,
                project_id=request.project_id,
                task_id=request.task_id,
                workflow_id=request.workflow_id,
                agent_id=self.metadata.id,
                event_type=event_type,
                message=message,
                metadata=metadata,
            )

        events = [
            event(
                t_start,
                "AGENT_STARTED",
                "Agent execution started",
                {"requestId": request.request_id},
            )
        ]
        if outcome == "COMPLETED":
            for art in artifacts:
                events.append(
                    event(
                        t_end,
                        "ARTIFACT_CREATED",
                        f"Artifact '{art.id}' created",
                        {"requestId": request.request_id, "artifactId": art.id},
                    )
                )
            events.append(
                event(
                    t_end,
                    "AGENT_COMPLETED",
                    "Agent execution completed",
                    {"requestId": request.request_id},
                )
            )
        else:
            events.append(
                event(
                    t_end,
                    "AGENT_FAILED",
                    "Agent execution failed",
                    {"requestId": request.request_id},
                )
            )
        return events

    def _execute_tracked(
        self,
        request: AgentRequest,
        tracker: ModelCallTracker,
        t_start: datetime,
    ) -> AgentResult:
        issues = self._check(request)

        if issues:
            t_end = self._runtime.clock()
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
            duration = max(0.0, (t_end - t_start).total_seconds())
            metrics = self._compute_metrics(request, duration, tracker)
            return AgentResult(
                request_id=request.request_id,
                agent_id=self.metadata.id,
                status="REJECTED",
                output=None,
                artifacts=[],
                events=[],
                metrics=metrics,
                errors=errors,
            )

        try:
            output, artifacts = self._run(request)
            t_end = self._runtime.clock()
            artifacts = [art.model_copy(update={"created_at": t_end}) for art in artifacts]

            events = self._lifecycle_events(request, t_start, t_end, "COMPLETED", artifacts)

            duration = max(0.0, (t_end - t_start).total_seconds())
            metrics = self._compute_metrics(request, duration, tracker)
            return AgentResult(
                request_id=request.request_id,
                agent_id=self.metadata.id,
                status="SUCCESS",
                output=output,
                artifacts=artifacts,
                events=events,
                metrics=metrics,
                errors=[],
            )

        except (ModelGatewayError, AgentExecutionError) as err:
            t_end = self._runtime.clock()
            # One console line per failed execution: the dashboard
            # banner shows only the headline message, so the recorded
            # details (the actual rejection cause) must reach the
            # backend terminal to be diagnosable at all.
            logger.warning(
                "agent %s failed: task=%s request=%s code=%s message=%s details=%s",
                self.metadata.id,
                request.task_id,
                request.request_id,
                err.code,
                err.message,
                json.dumps(err.details, default=str)[:600] if err.details else "-",
            )
            p_err = PlatformError.model_validate(err.to_platform_error(t_end))
            events = self._lifecycle_events(request, t_start, t_end, "FAILED", [])
            duration = max(0.0, (t_end - t_start).total_seconds())
            metrics = self._compute_metrics(request, duration, tracker)
            if isinstance(err, AgentExecutionError) and err.status == "REJECTED":
                events = []
            return AgentResult(
                request_id=request.request_id,
                agent_id=self.metadata.id,
                status=err.status if isinstance(err, AgentExecutionError) else "FAILED",
                output=None,
                artifacts=[],
                events=events,
                metrics=metrics,
                errors=[p_err],
            )

        except Exception as exc:
            t_end = self._runtime.clock()
            p_err = PlatformError(
                code="AGENT_EXECUTION_FAILED",
                message="Agent execution failed",
                category="AGENT",
                details={"exceptionType": type(exc).__name__},
                retryable=True,
                timestamp=t_end,
            )
            events = self._lifecycle_events(request, t_start, t_end, "FAILED", [])
            duration = max(0.0, (t_end - t_start).total_seconds())
            metrics = self._compute_metrics(request, duration, tracker)
            return AgentResult(
                request_id=request.request_id,
                agent_id=self.metadata.id,
                status="FAILED",
                output=None,
                artifacts=[],
                events=events,
                metrics=metrics,
                errors=[p_err],
            )
