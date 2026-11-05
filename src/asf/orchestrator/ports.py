from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any, Protocol

from asf.approval.ports import ApprovalRepository
from asf.contracts.models import ActivityEvent, AgentResult
from asf.orchestrator.execution import WorkflowExecution


class ConcurrentModificationError(RuntimeError):
    """A stored execution changed since it was read.

    Raised by execution stores when a version-guarded save matches no
    row, and by the orchestrator when a claimed dispatch no longer owns
    its run at commit time. The write is refused instead of silently
    overwriting the other writer's state (a lost update).
    """


class ExecutionStore(Protocol):
    @property
    def approvals(self) -> ApprovalRepository: ...

    def transaction(self) -> AbstractContextManager[None]: ...

    def create_execution(self, run: WorkflowExecution) -> None: ...

    def save_execution(self, run: WorkflowExecution) -> None: ...

    def get_execution(
        self, run_id: str, *, for_update: bool = False,
    ) -> WorkflowExecution: ...

    def list_executions(self, project_id: str) -> list[WorkflowExecution]: ...

    def list_execution_summaries(
        self,
        project_id: str | None = None,
        *,
        status: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Lightweight run rows WITHOUT payloads (id, project, task,
        workflow, stage/status, started/updated timestamps).

        List views and store discovery use these to avoid loading and
        deserializing every run's full payload per request; a full
        execution is fetched only when it is new/changed or a detail
        view needs it. ``status`` filters on the store-level status,
        which mirrors the run's stage.
        """
        ...


class EventPublisher(Protocol):
    def publish(self, event: ActivityEvent) -> None: ...


class MetricsRecorder(Protocol):
    def record(self, agent_id: str, result: AgentResult) -> None: ...
