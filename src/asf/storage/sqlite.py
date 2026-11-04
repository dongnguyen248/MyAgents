from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from asf.approval.models import ApprovalDecision, ApprovalRequest
from asf.orchestrator.execution import WorkflowExecution


class SQLiteApprovalRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def create(self, approval: ApprovalRequest) -> ApprovalRequest:
        self._connection.execute(
            "INSERT INTO approvals(id, payload) VALUES (?, ?)",
            (approval.id, approval.model_dump_json()),
        )
        return approval.model_copy(deep=True)

    def get(self, approval_id: str) -> ApprovalRequest | None:
        row = self._connection.execute(
            "SELECT payload FROM approvals WHERE id = ?", (approval_id,),
        ).fetchone()
        return ApprovalRequest.model_validate_json(row[0]) if row else None

    def update(self, approval: ApprovalRequest) -> ApprovalRequest:
        cursor = self._connection.execute(
            "UPDATE approvals SET payload = ? WHERE id = ?",
            (approval.model_dump_json(), approval.id),
        )
        if cursor.rowcount != 1:
            raise KeyError(approval.id)
        return approval.model_copy(deep=True)

    def _all(self) -> list[ApprovalRequest]:
        rows = self._connection.execute("SELECT payload FROM approvals").fetchall()
        return sorted(
            [ApprovalRequest.model_validate_json(row[0]) for row in rows],
            key=lambda approval: (approval.requested_at, approval.id),
        )

    def list_by_task(self, task_id: str) -> list[ApprovalRequest]:
        return [approval for approval in self._all() if approval.task_id == task_id]

    def list_pending(self) -> list[ApprovalRequest]:
        return [approval for approval in self._all() if approval.status == "PENDING"]

    def add_decision(self, decision: ApprovalDecision) -> None:
        self._connection.execute(
            "INSERT INTO decisions(approval_id, payload) VALUES (?, ?)",
            (decision.approval_id, decision.model_dump_json()),
        )

    def list_decisions(self, approval_id: str) -> list[ApprovalDecision]:
        rows = self._connection.execute(
            "SELECT payload FROM decisions WHERE approval_id = ? ORDER BY sequence",
            (approval_id,),
        ).fetchall()
        return [ApprovalDecision.model_validate_json(row[0]) for row in rows]


class SQLiteExecutionStore:
    """One local worker; workflow checkpoints and approvals share a transaction."""

    def __init__(self, path: str | Path) -> None:
        self._connection = sqlite3.connect(path, isolation_level=None)
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS executions (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL, payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS approvals (
                id TEXT PRIMARY KEY, payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS decisions (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                approval_id TEXT NOT NULL REFERENCES approvals(id), payload TEXT NOT NULL
            );
            """
        )
        self.approvals = SQLiteApprovalRepository(self._connection)

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            yield
            self._connection.commit()
        except BaseException:
            self._connection.rollback()
            raise

    def create_execution(self, run: WorkflowExecution) -> None:
        self._connection.execute(
            "INSERT INTO executions(id, project_id, payload) VALUES (?, ?, ?)",
            (run.id, run.project_id, run.model_dump_json()),
        )

    def save_execution(self, run: WorkflowExecution) -> None:
        cursor = self._connection.execute(
            "UPDATE executions SET payload = ? WHERE id = ?",
            (run.model_dump_json(), run.id),
        )
        if cursor.rowcount != 1:
            raise KeyError(run.id)

    def get_execution(self, run_id: str) -> WorkflowExecution:
        row = self._connection.execute(
            "SELECT payload FROM executions WHERE id = ?", (run_id,),
        ).fetchone()
        if row is None:
            raise KeyError(run_id)
        return WorkflowExecution.model_validate_json(row[0])

    def list_executions(self, project_id: str) -> list[WorkflowExecution]:
        rows = self._connection.execute(
            "SELECT payload FROM executions WHERE project_id = ? ORDER BY id", (project_id,),
        ).fetchall()
        return [WorkflowExecution.model_validate_json(row[0]) for row in rows]

    def close(self) -> None:
        self._connection.close()
