from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Protocol

from asf.approval.ports import ApprovalRepository
from asf.contracts.models import ActivityEvent, AgentResult
from asf.orchestrator.execution import WorkflowExecution


class ExecutionStore(Protocol):
    @property
    def approvals(self) -> ApprovalRepository: ...

    def transaction(self) -> AbstractContextManager[None]: ...

    def create_execution(self, run: WorkflowExecution) -> None: ...

    def save_execution(self, run: WorkflowExecution) -> None: ...

    def get_execution(self, run_id: str) -> WorkflowExecution: ...

    def list_executions(self, project_id: str) -> list[WorkflowExecution]: ...


class EventPublisher(Protocol):
    def publish(self, event: ActivityEvent) -> None: ...


class MetricsRecorder(Protocol):
    def record(self, agent_id: str, result: AgentResult) -> None: ...
