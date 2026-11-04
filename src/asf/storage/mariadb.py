"""MariaDB-backed execution store.

Same contract as :mod:`asf.storage.sqlite` — one connection, autocommit
outside explicit transactions, JSON payloads — over a MariaDB server, for
deployments that outgrow a local SQLite file. The driver (PyMySQL) is
imported lazily so SQLite users never need it installed.

Startup is self-migrating: connecting creates the database when missing
and applies any pending schema migrations, so the only manual setup is a
MariaDB account with privileges on the application database (e.g.
``GRANT ALL PRIVILEGES ON asf.* TO 'asf'@'localhost'`` — the grant alone
is enough, the database itself does not have to exist beforehand).
Connection settings come from the ``ASF_MARIADB_*`` environment variables
(host, port, user, password, database); the password is never accepted
from the command line or a file.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from asf.approval.models import ApprovalDecision, ApprovalRequest
from asf.orchestrator.execution import WorkflowExecution

_DATABASE_NAME = re.compile(r"^[A-Za-z0-9_]+$")

# Ordered schema migrations, applied once at store open and recorded in
# the schema_migrations table. Statements stay idempotent (IF NOT EXISTS)
# so a crash mid-migration can simply be retried on the next start.
_MIGRATIONS: tuple[tuple[int, tuple[str, ...]], ...] = (
    (1, (
        """
        CREATE TABLE IF NOT EXISTS executions (
            id VARCHAR(64) PRIMARY KEY,
            project_id VARCHAR(191) NOT NULL,
            payload LONGTEXT NOT NULL,
            KEY idx_executions_project (project_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS approvals (
            id VARCHAR(64) PRIMARY KEY,
            payload LONGTEXT NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS decisions (
            sequence BIGINT PRIMARY KEY AUTO_INCREMENT,
            approval_id VARCHAR(64) NOT NULL,
            payload LONGTEXT NOT NULL,
            KEY idx_decisions_approval (approval_id),
            CONSTRAINT fk_decisions_approval
                FOREIGN KEY (approval_id) REFERENCES approvals (id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
    )),
)


@dataclass(frozen=True)
class MariaDbConfig:
    """Connection settings for the MariaDB store (env-driven)."""

    host: str = "127.0.0.1"
    port: int = 3306
    user: str = "asf"
    password: str = ""
    database: str = "asf"

    @classmethod
    def from_env(cls) -> MariaDbConfig:
        return cls(
            host=os.environ.get("ASF_MARIADB_HOST", "127.0.0.1"),
            port=int(os.environ.get("ASF_MARIADB_PORT", "3306")),
            user=os.environ.get("ASF_MARIADB_USER", "asf"),
            password=os.environ.get("ASF_MARIADB_PASSWORD", ""),
            database=os.environ.get("ASF_MARIADB_DATABASE", "asf"),
        )


class MariaDbApprovalRepository:
    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def create(self, approval: ApprovalRequest) -> ApprovalRequest:
        with self._connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO approvals(id, payload) VALUES (%s, %s)",
                (approval.id, approval.model_dump_json()),
            )
        return approval.model_copy(deep=True)

    def get(self, approval_id: str) -> ApprovalRequest | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT payload FROM approvals WHERE id = %s", (approval_id,),
            )
            row = cursor.fetchone()
        return ApprovalRequest.model_validate_json(row[0]) if row else None

    def update(self, approval: ApprovalRequest) -> ApprovalRequest:
        with self._connection.cursor() as cursor:
            cursor.execute(
                "UPDATE approvals SET payload = %s WHERE id = %s",
                (approval.model_dump_json(), approval.id),
            )
            if cursor.rowcount != 1:
                raise KeyError(approval.id)
        return approval.model_copy(deep=True)

    def _all(self) -> list[ApprovalRequest]:
        with self._connection.cursor() as cursor:
            cursor.execute("SELECT payload FROM approvals")
            rows = cursor.fetchall()
        return sorted(
            [ApprovalRequest.model_validate_json(row[0]) for row in rows],
            key=lambda approval: (approval.requested_at, approval.id),
        )

    def list_by_task(self, task_id: str) -> list[ApprovalRequest]:
        return [approval for approval in self._all() if approval.task_id == task_id]

    def list_pending(self) -> list[ApprovalRequest]:
        return [approval for approval in self._all() if approval.status == "PENDING"]

    def add_decision(self, decision: ApprovalDecision) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO decisions(approval_id, payload) VALUES (%s, %s)",
                (decision.approval_id, decision.model_dump_json()),
            )

    def list_decisions(self, approval_id: str) -> list[ApprovalDecision]:
        with self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT payload FROM decisions WHERE approval_id = %s"
                " ORDER BY sequence",
                (approval_id,),
            )
            rows = cursor.fetchall()
        return [ApprovalDecision.model_validate_json(row[0]) for row in rows]


class MariaDbExecutionStore:
    """One local worker; workflow checkpoints and approvals share a transaction."""

    def __init__(self, config: MariaDbConfig) -> None:
        if not _DATABASE_NAME.match(config.database):
            raise ValueError(
                f"Invalid MariaDB database name {config.database!r}:"
                " letters, digits and underscores only",
            )
        self._config = config
        self._connection = self._open()
        self._migrate()
        self.approvals = MariaDbApprovalRepository(self._connection)

    # -- connection & migrations -------------------------------------------
    def _connect(self, *, database: str | None) -> Any:
        try:
            import pymysql
            from pymysql.constants import CLIENT
        except ImportError as error:
            raise RuntimeError(
                "MariaDB support needs the PyMySQL driver:"
                " python -m pip install pymysql"
                " (or pip install 'ai-software-agents[mariadb]')",
            ) from error
        try:
            return pymysql.connect(
                host=self._config.host,
                port=self._config.port,
                user=self._config.user,
                password=self._config.password,
                database=database,
                charset="utf8mb4",
                autocommit=True,
                # FOUND_ROWS: an UPDATE's rowcount must count matched rows
                # (SQLite semantics the store contract assumes), not only
                # rows whose values actually changed.
                client_flag=CLIENT.FOUND_ROWS,
            )
        except Exception as error:
            raise RuntimeError(
                f"Cannot connect to MariaDB at {self._config.host}:"
                f"{self._config.port} as '{self._config.user}' — check the"
                " server is running and ASF_MARIADB_HOST / ASF_MARIADB_PORT /"
                " ASF_MARIADB_USER / ASF_MARIADB_PASSWORD are set correctly"
                f" (server said: {error})",
            ) from error

    def _open(self) -> Any:
        # Connect without a database first so a missing one can be created:
        # a db-level grant (GRANT ... ON asf.*) is enough for this, the
        # database itself does not have to exist beforehand.
        server = self._connect(database=None)
        try:
            with server.cursor() as cursor:
                cursor.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{self._config.database}`"
                    " DEFAULT CHARACTER SET utf8mb4",
                )
        finally:
            server.close()
        return self._connect(database=self._config.database)

    def _migrate(self) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INT PRIMARY KEY,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """,
            )
            cursor.execute("SELECT version FROM schema_migrations")
            applied = {row[0] for row in cursor.fetchall()}
            for version, statements in _MIGRATIONS:
                if version in applied:
                    continue
                for statement in statements:
                    cursor.execute(statement)
                cursor.execute(
                    "INSERT INTO schema_migrations(version) VALUES (%s)",
                    (version,),
                )

    # -- executions ---------------------------------------------------------
    @contextmanager
    def transaction(self) -> Iterator[None]:
        self._connection.begin()
        try:
            yield
            self._connection.commit()
        except BaseException:
            self._connection.rollback()
            raise

    def create_execution(self, run: WorkflowExecution) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO executions(id, project_id, payload)"
                " VALUES (%s, %s, %s)",
                (run.id, run.project_id, run.model_dump_json()),
            )

    def save_execution(self, run: WorkflowExecution) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                "UPDATE executions SET payload = %s WHERE id = %s",
                (run.model_dump_json(), run.id),
            )
            if cursor.rowcount != 1:
                raise KeyError(run.id)

    def get_execution(self, run_id: str) -> WorkflowExecution:
        with self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT payload FROM executions WHERE id = %s", (run_id,),
            )
            row = cursor.fetchone()
        if row is None:
            raise KeyError(run_id)
        return WorkflowExecution.model_validate_json(row[0])

    def list_executions(self, project_id: str) -> list[WorkflowExecution]:
        with self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT payload FROM executions WHERE project_id = %s"
                " ORDER BY id",
                (project_id,),
            )
            rows = cursor.fetchall()
        return [WorkflowExecution.model_validate_json(row[0]) for row in rows]

    def close(self) -> None:
        self._connection.close()
