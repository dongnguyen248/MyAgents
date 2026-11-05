from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Any

from asf.approval.models import ApprovalDecision, ApprovalRequest
from asf.orchestrator.execution import WorkflowExecution


class SQLiteApprovalRepository:
    def __init__(
        self,
        connect: Callable[[], sqlite3.Connection],
        lock: threading.RLock | None,
    ) -> None:
        self._connect = connect
        self._lock = lock

    @contextmanager
    def _guard(self) -> Iterator[None]:
        # A shared (":memory:") connection is serialized; a per-thread
        # connection needs no guard at all.
        with self._lock if self._lock is not None else nullcontext():
            yield

    def create(self, approval: ApprovalRequest) -> ApprovalRequest:
        with self._guard():
            self._connect().execute(
                "INSERT INTO approvals(id, payload) VALUES (?, ?)",
                (approval.id, approval.model_dump_json()),
            )
        return approval.model_copy(deep=True)

    def get(self, approval_id: str) -> ApprovalRequest | None:
        with self._guard():
            row = (
                self._connect()
                .execute(
                    "SELECT payload FROM approvals WHERE id = ?",
                    (approval_id,),
                )
                .fetchone()
            )
        return ApprovalRequest.model_validate_json(row[0]) if row else None

    def update(self, approval: ApprovalRequest) -> ApprovalRequest:
        with self._guard():
            cursor = self._connect().execute(
                "UPDATE approvals SET payload = ? WHERE id = ?",
                (approval.model_dump_json(), approval.id),
            )
            if cursor.rowcount != 1:
                raise KeyError(approval.id)
        return approval.model_copy(deep=True)

    def _all(self) -> list[ApprovalRequest]:
        with self._guard():
            rows = self._connect().execute("SELECT payload FROM approvals").fetchall()
        return sorted(
            [ApprovalRequest.model_validate_json(row[0]) for row in rows],
            key=lambda approval: (approval.requested_at, approval.id),
        )

    def list_by_task(self, task_id: str) -> list[ApprovalRequest]:
        return [approval for approval in self._all() if approval.task_id == task_id]

    def list_pending(self) -> list[ApprovalRequest]:
        return [approval for approval in self._all() if approval.status == "PENDING"]

    def add_decision(self, decision: ApprovalDecision) -> None:
        with self._guard():
            self._connect().execute(
                "INSERT INTO decisions(approval_id, payload) VALUES (?, ?)",
                (decision.approval_id, decision.model_dump_json()),
            )

    def list_decisions(self, approval_id: str) -> list[ApprovalDecision]:
        with self._guard():
            rows = (
                self._connect()
                .execute(
                    "SELECT payload FROM decisions WHERE approval_id = ? ORDER BY sequence",
                    (approval_id,),
                )
                .fetchall()
            )
        return [ApprovalDecision.model_validate_json(row[0]) for row in rows]


class SQLiteExecutionStore:
    """Workflow checkpoints and approvals in one SQLite file.

    One connection per thread: run drives execute agent steps on a
    background thread while the API keeps serving reads on its request
    threads, and sqlite3 connections are single-thread objects. Each
    connection sets a busy timeout so a concurrent writer queues
    briefly instead of failing with "database is locked". A ":memory:"
    database cannot be shared that way, so it falls back to one shared
    connection serialized by a lock (test use only).
    """

    def __init__(self, path: str | Path) -> None:
        # sqlite3 creates the database file but not its parent directories,
        # so a path like data/asf.sqlite fails on a fresh checkout unless
        # the caller created data/ first. Create them here instead.
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._shared = str(path) == ":memory:"
        self._lock = threading.RLock() if self._shared else None
        self._local = threading.local()
        if self._shared:
            self._shared_connection = sqlite3.connect(
                ":memory:",
                isolation_level=None,
                check_same_thread=False,
            )
            self._configure(self._shared_connection)
        self._connection().executescript(
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
        self.approvals = SQLiteApprovalRepository(self._connection, self._lock)

    @staticmethod
    def _configure(connection: sqlite3.Connection) -> None:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")

    def _connection(self) -> sqlite3.Connection:
        if self._shared:
            return self._shared_connection
        connection = getattr(self._local, "connection", None)
        if connection is None:
            connection = sqlite3.connect(self._path, isolation_level=None)
            self._configure(connection)
            connection.execute("PRAGMA journal_mode = WAL")
            self._local.connection = connection
        return connection

    @contextmanager
    def _guard(self) -> Iterator[None]:
        with self._lock if self._lock is not None else nullcontext():
            yield

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self._guard():
            connection = self._connection()
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def create_execution(self, run: WorkflowExecution) -> None:
        with self._guard():
            self._connection().execute(
                "INSERT INTO executions(id, project_id, payload) VALUES (?, ?, ?)",
                (run.id, run.project_id, run.model_dump_json()),
            )

    def save_execution(self, run: WorkflowExecution) -> None:
        with self._guard():
            cursor = self._connection().execute(
                "UPDATE executions SET payload = ? WHERE id = ?",
                (run.model_dump_json(), run.id),
            )
            if cursor.rowcount != 1:
                raise KeyError(run.id)

    def get_execution(
        self,
        run_id: str,
        *,
        for_update: bool = False,
    ) -> WorkflowExecution:
        # for_update is accepted for ExecutionStore compatibility and
        # ignored: locking reads are a MariaDB-store concern; this
        # store's transaction() already serializes writers.
        with self._guard():
            row = (
                self._connection()
                .execute(
                    "SELECT payload FROM executions WHERE id = ?",
                    (run_id,),
                )
                .fetchone()
            )
        if row is None:
            raise KeyError(run_id)
        return WorkflowExecution.model_validate_json(row[0])

    def list_executions(self, project_id: str) -> list[WorkflowExecution]:
        with self._guard():
            rows = (
                self._connection()
                .execute(
                    "SELECT payload FROM executions WHERE project_id = ? ORDER BY id",
                    (project_id,),
                )
                .fetchall()
            )
        return [WorkflowExecution.model_validate_json(row[0]) for row in rows]

    def list_execution_summaries(
        self,
        project_id: str | None = None,
        *,
        status: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Summary rows via SQLite's JSON1 extraction: the payload
        text is never materialized into Python objects. (Unlike the
        MariaDB store there are no metadata columns or indexes here —
        this is the local development store; the extraction keeps the
        per-request cost proportional to the row count, not the
        payload sizes.)"""
        clauses: list[str] = []
        params: list[Any] = []
        if project_id is not None:
            clauses.append("project_id = ?")
            params.append(project_id)
        if status is not None:
            clauses.append("json_extract(payload, '$.state.stage') = ?")
            params.append(status)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = (
            "SELECT id, project_id,"
            " json_extract(payload, '$.task_id'),"
            " json_extract(payload, '$.definition.id'),"
            " json_extract(payload, '$.state.stage'),"
            " json_extract(payload, '$.started_at'),"
            " json_extract(payload, '$.updated_at')"
            f" FROM executions{where}"
            " ORDER BY json_extract(payload, '$.updated_at'), id"
        )
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])
        elif offset:
            sql += " LIMIT -1 OFFSET ?"
            params.append(offset)
        with self._guard():
            rows = self._connection().execute(sql, params).fetchall()
        return [
            {
                "id": row[0],
                "projectId": row[1],
                "taskId": row[2],
                "workflowId": row[3],
                "stage": row[4],
                "status": row[4],
                "startedAt": row[5],
                "updatedAt": row[6],
            }
            for row in rows
        ]

    def close(self) -> None:
        # Closes the calling thread's connection; per-thread connections
        # of other (daemon) threads end with the process.
        if self._shared:
            self._shared_connection.close()
        else:
            connection = getattr(self._local, "connection", None)
            if connection is not None:
                connection.close()
                self._local.connection = None
