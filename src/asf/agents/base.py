from __future__ import annotations

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
from asf.models.errors import ModelGatewayError
from asf.models.ports import ModelGateway

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
            "code": self.code, "message": self.message, "category": self.category,
            "retryable": self.retryable, "details": self.details, "timestamp": now,
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

    def _compute_metrics(self, request: AgentRequest, duration_seconds: float) -> RunMetrics:
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
        """Executes the agent workflow according to platform rules."""
        t_start = self._runtime.clock()
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
            metrics = self._compute_metrics(request, duration)
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

            events = [
                ActivityEvent(
                    id=self._runtime.new_id(),
                    timestamp=t_start,
                    project_id=request.project_id,
                    task_id=request.task_id,
                    workflow_id=request.workflow_id,
                    agent_id=self.metadata.id,
                    event_type="AGENT_STARTED",
                    message="Agent execution started",
                    metadata={"requestId": request.request_id},
                )
            ]

            for art in artifacts:
                events.append(
                    ActivityEvent(
                        id=self._runtime.new_id(),
                        timestamp=t_end,
                        project_id=request.project_id,
                        task_id=request.task_id,
                        workflow_id=request.workflow_id,
                        agent_id=self.metadata.id,
                        event_type="ARTIFACT_CREATED",
                        message=f"Artifact '{art.id}' created",
                        metadata={"requestId": request.request_id, "artifactId": art.id},
                    )
                )

            events.append(
                ActivityEvent(
                    id=self._runtime.new_id(),
                    timestamp=t_end,
                    project_id=request.project_id,
                    task_id=request.task_id,
                    workflow_id=request.workflow_id,
                    agent_id=self.metadata.id,
                    event_type="AGENT_COMPLETED",
                    message="Agent execution completed",
                    metadata={"requestId": request.request_id},
                )
            )

            duration = max(0.0, (t_end - t_start).total_seconds())
            metrics = self._compute_metrics(request, duration)
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
            p_err = PlatformError.model_validate(err.to_platform_error(t_end))
            events = [
                ActivityEvent(
                    id=self._runtime.new_id(),
                    timestamp=t_start,
                    project_id=request.project_id,
                    task_id=request.task_id,
                    workflow_id=request.workflow_id,
                    agent_id=self.metadata.id,
                    event_type="AGENT_STARTED",
                    message="Agent execution started",
                    metadata={"requestId": request.request_id},
                ),
                ActivityEvent(
                    id=self._runtime.new_id(),
                    timestamp=t_end,
                    project_id=request.project_id,
                    task_id=request.task_id,
                    workflow_id=request.workflow_id,
                    agent_id=self.metadata.id,
                    event_type="AGENT_FAILED",
                    message="Agent execution failed",
                    metadata={"requestId": request.request_id},
                ),
            ]
            duration = max(0.0, (t_end - t_start).total_seconds())
            metrics = self._compute_metrics(request, duration)
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
            events = [
                ActivityEvent(
                    id=self._runtime.new_id(),
                    timestamp=t_start,
                    project_id=request.project_id,
                    task_id=request.task_id,
                    workflow_id=request.workflow_id,
                    agent_id=self.metadata.id,
                    event_type="AGENT_STARTED",
                    message="Agent execution started",
                    metadata={"requestId": request.request_id},
                ),
                ActivityEvent(
                    id=self._runtime.new_id(),
                    timestamp=t_end,
                    project_id=request.project_id,
                    task_id=request.task_id,
                    workflow_id=request.workflow_id,
                    agent_id=self.metadata.id,
                    event_type="AGENT_FAILED",
                    message="Agent execution failed",
                    metadata={"requestId": request.request_id},
                ),
            ]
            duration = max(0.0, (t_end - t_start).total_seconds())
            metrics = self._compute_metrics(request, duration)
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
