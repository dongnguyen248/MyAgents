from __future__ import annotations

import copy
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from asf.approval.models import ApprovalDecision, ApprovalRequest
from asf.orchestrator.execution import WorkflowExecution
from asf.orchestrator.ports import ConcurrentModificationError

__all__ = ["InMemoryApprovalRepository", "InMemoryStore"]


class InMemoryApprovalRepository:
    """In-memory implementation of ApprovalRepository protocol.

    Stores deep copies and returns deep copies so mutations outside the repository
    never affect internal state.

    Updating an unknown approval id raises KeyError.
    """

    def __init__(self) -> None:
        self._approvals: dict[str, ApprovalRequest] = {}
        self._decisions: dict[str, list[ApprovalDecision]] = {}

    def create(self, approval: ApprovalRequest) -> ApprovalRequest:
        self._approvals[approval.id] = copy.deepcopy(approval)
        return copy.deepcopy(approval)

    def get(self, approval_id: str) -> ApprovalRequest | None:
        approval = self._approvals.get(approval_id)
        if approval is None:
            return None
        return copy.deepcopy(approval)

    def update(self, approval: ApprovalRequest) -> ApprovalRequest:
        if approval.id not in self._approvals:
            raise KeyError(f"ApprovalRequest with id '{approval.id}' does not exist")
        self._approvals[approval.id] = copy.deepcopy(approval)
        return copy.deepcopy(approval)

    def list_by_task(self, task_id: str) -> list[ApprovalRequest]:
        matching = [req for req in self._approvals.values() if req.task_id == task_id]
        matching.sort(key=lambda r: (r.requested_at, r.id))
        return [copy.deepcopy(r) for r in matching]

    def list_pending(self) -> list[ApprovalRequest]:
        matching = [req for req in self._approvals.values() if req.status == "PENDING"]
        matching.sort(key=lambda r: (r.requested_at, r.id))
        return [copy.deepcopy(r) for r in matching]

    def add_decision(self, decision: ApprovalDecision) -> None:
        if decision.approval_id not in self._decisions:
            self._decisions[decision.approval_id] = []
        self._decisions[decision.approval_id].append(copy.deepcopy(decision))

    def list_decisions(self, approval_id: str) -> list[ApprovalDecision]:
        decisions = self._decisions.get(approval_id, [])
        return [copy.deepcopy(d) for d in decisions]


class InMemoryStore:
    """In-memory ``ExecutionStore`` — tests and ephemeral demos only.

    Mirrors the MariaDB store's contract (the production store):
    ``create_execution`` resets the run's version to 0 and refuses
    duplicate ids; ``save_execution`` is version-guarded — it bumps
    the passed run's version by one and stores it only when the
    stored version still equals the version the caller read,
    raising ``KeyError`` for an unknown id and
    ``ConcurrentModificationError`` for a stale writer;
    ``transaction()`` snapshots the whole store and rolls back on
    error. Nothing survives the process, which is exactly why real
    runs must use MariaDB.

    One re-entrant lock serializes everything: this store favors
    obvious correctness over parallelism.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._executions: dict[str, WorkflowExecution] = {}
        self._tx_depth = 0
        self._snapshot: (
            tuple[
                dict[str, WorkflowExecution],
                dict[str, ApprovalRequest],
                dict[str, list[ApprovalDecision]],
            ]
            | None
        ) = None
        self.approvals = InMemoryApprovalRepository()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        # The snapshot covers the approvals repository as well as
        # the executions: in the database stores both live in one
        # database, so one transaction rolls back decisions and
        # checkpoints together — the same atomicity must hold here.
        with self._lock:
            if self._tx_depth == 0:
                self._snapshot = (
                    copy.deepcopy(self._executions),
                    copy.deepcopy(self.approvals._approvals),
                    copy.deepcopy(self.approvals._decisions),
                )
            self._tx_depth += 1
            try:
                yield
            except BaseException:
                if self._snapshot is not None:
                    executions, approvals, decisions = self._snapshot
                    self._executions = executions
                    self.approvals._approvals = approvals
                    self.approvals._decisions = decisions
                    self._snapshot = None
                    self._tx_depth = 0
                raise
            self._tx_depth -= 1
            if self._tx_depth == 0:
                self._snapshot = None

    def create_execution(self, run: WorkflowExecution) -> None:
        with self._lock:
            if run.id in self._executions:
                raise ValueError(f"execution already exists: {run.id}")
            run.version = 0
            self._executions[run.id] = copy.deepcopy(run)

    def save_execution(self, run: WorkflowExecution) -> None:
        with self._lock:
            stored = self._executions.get(run.id)
            if stored is None:
                raise KeyError(run.id)
            if stored.version != run.version:
                raise ConcurrentModificationError(
                    f"execution {run.id} changed since it was read "
                    f"(stored version {stored.version}, saving {run.version})"
                )
            run.version += 1
            self._executions[run.id] = copy.deepcopy(run)

    def get_execution(
        self,
        run_id: str,
        *,
        for_update: bool = False,
    ) -> WorkflowExecution:
        # for_update is accepted for protocol compatibility; the
        # store-wide lock already serializes writers.
        with self._lock:
            run = self._executions.get(run_id)
            if run is None:
                raise KeyError(run_id)
            return copy.deepcopy(run)

    def list_executions(self, project_id: str) -> list[WorkflowExecution]:
        with self._lock:
            return [
                copy.deepcopy(run)
                for run in sorted(self._executions.values(), key=lambda r: r.id)
                if run.project_id == project_id
            ]

    def list_execution_summaries(
        self,
        project_id: str | None = None,
        *,
        status: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        with self._lock:
            rows = [
                {
                    "id": run.id,
                    "projectId": run.project_id,
                    "taskId": run.task_id,
                    "workflowId": run.definition.get("id"),
                    "stage": run.state.stage,
                    "status": run.state.stage,
                    "startedAt": run.started_at.isoformat(),
                    "updatedAt": run.updated_at.isoformat(),
                }
                for run in self._executions.values()
                if (project_id is None or run.project_id == project_id)
                and (status is None or run.state.stage == status)
            ]
        rows.sort(key=lambda row: (row["updatedAt"], row["id"]))
        if offset:
            rows = rows[offset:]
        if limit is not None:
            rows = rows[:limit]
        return rows

    def close(self) -> None:
        """Nothing to release; present for protocol symmetry."""
