"""MariaDB-backed execution store.

Same contract as :mod:`asf.storage.sqlite` — one connection per
thread, autocommit outside explicit transactions, JSON payloads — over
a MariaDB server, for
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

import logging
import os
import re
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from asf.approval.models import ApprovalDecision, ApprovalRequest
from asf.orchestrator.execution import WorkflowExecution
from asf.orchestrator.ports import ConcurrentModificationError

logger = logging.getLogger(__name__)

_DATABASE_NAME = re.compile(r"^[A-Za-z0-9_]+$")

# Ordered schema migrations, applied once at store open and recorded in
# the schema_migrations table. Statements stay idempotent (IF NOT EXISTS)
# so a crash mid-migration can simply be retried on the next start.
_MIGRATIONS: tuple[tuple[int, tuple[str, ...]], ...] = (
    (
        1,
        (
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
        ),
    ),
    (
        2,
        (
            # Optimistic locking for executions: saves are guarded by the
            # version the writer read, so concurrent writers cannot
            # silently overwrite each other (lost update).
            """
        ALTER TABLE executions ADD COLUMN IF NOT EXISTS
            version INT NOT NULL DEFAULT 0
        """,
        ),
    ),
    (
        3,
        (
            # Queryable metadata columns for executions: list views and
            # store discovery read these instead of deserializing every
            # run's payload. save/create keep them in step with the
            # payload; the UPDATE below backfills rows written before
            # this migration (payloads are JSON text, so the values are
            # extracted from the payload itself).
            "ALTER TABLE executions ADD COLUMN IF NOT EXISTS task_id VARCHAR(191) NULL",
            "ALTER TABLE executions ADD COLUMN IF NOT EXISTS stage VARCHAR(64) NULL",
            "ALTER TABLE executions ADD COLUMN IF NOT EXISTS status VARCHAR(64) NULL",
            "ALTER TABLE executions ADD COLUMN IF NOT EXISTS workflow_id VARCHAR(191) NULL",
            "ALTER TABLE executions ADD COLUMN IF NOT EXISTS started_at DATETIME(6) NULL",
            "ALTER TABLE executions ADD COLUMN IF NOT EXISTS updated_at DATETIME(6) NULL",
            """
        UPDATE executions SET
            task_id = JSON_UNQUOTE(JSON_EXTRACT(payload, '$.task_id')),
            stage = JSON_UNQUOTE(JSON_EXTRACT(payload, '$.state.stage')),
            status = JSON_UNQUOTE(JSON_EXTRACT(payload, '$.state.stage')),
            workflow_id = JSON_UNQUOTE(JSON_EXTRACT(payload, '$.definition.id')),
            started_at = CAST(REPLACE(LEFT(
                JSON_UNQUOTE(JSON_EXTRACT(payload, '$.started_at')), 19
            ), 'T', ' ') AS DATETIME(6)),
            updated_at = CAST(REPLACE(LEFT(
                JSON_UNQUOTE(JSON_EXTRACT(payload, '$.updated_at')), 19
            ), 'T', ' ') AS DATETIME(6))
        WHERE task_id IS NULL
        """,
            """
        ALTER TABLE executions ADD INDEX IF NOT EXISTS
            idx_executions_project_updated (project_id, updated_at)
        """,
            "ALTER TABLE executions ADD INDEX IF NOT EXISTS idx_executions_status (status)",
            # Approvals get the same treatment: list_pending/list_by_task
            # become indexed WHERE queries instead of loading every
            # approval payload and filtering in Python.
            "ALTER TABLE approvals ADD COLUMN IF NOT EXISTS status VARCHAR(32) NULL",
            "ALTER TABLE approvals ADD COLUMN IF NOT EXISTS task_id VARCHAR(191) NULL",
            "ALTER TABLE approvals ADD COLUMN IF NOT EXISTS requested_at DATETIME(6) NULL",
            """
        UPDATE approvals SET
            status = JSON_UNQUOTE(JSON_EXTRACT(payload, '$.status')),
            task_id = JSON_UNQUOTE(JSON_EXTRACT(payload, '$.task_id')),
            requested_at = CAST(REPLACE(LEFT(
                JSON_UNQUOTE(JSON_EXTRACT(payload, '$.requested_at')), 19
            ), 'T', ' ') AS DATETIME(6))
        WHERE status IS NULL
        """,
            "ALTER TABLE approvals ADD INDEX IF NOT EXISTS idx_approvals_status (status)",
            "ALTER TABLE approvals ADD INDEX IF NOT EXISTS idx_approvals_task (task_id)",
        ),
    ),
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


def _as_utc_naive(value: datetime) -> datetime:
    """DATETIME columns hold UTC wall time (payloads stay the truth)."""
    return value.astimezone(UTC).replace(tzinfo=None)


def _as_utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _execution_columns(run: WorkflowExecution) -> tuple[Any, ...]:
    """The queryable metadata columns for one execution row."""
    workflow_id = run.definition.get("id") if isinstance(run.definition, dict) else None
    return (
        run.task_id,
        run.state.stage,
        run.state.stage,  # status mirrors the stage at the store level
        workflow_id if isinstance(workflow_id, str) else None,
        _as_utc_naive(run.started_at),
        _as_utc_naive(run.updated_at),
    )


class MariaDbApprovalRepository:
    def __init__(self, connect: Callable[[], Any]) -> None:
        self._connect = connect

    def create(self, approval: ApprovalRequest) -> ApprovalRequest:
        with self._connect().cursor() as cursor:
            cursor.execute(
                "INSERT INTO approvals(id, payload, status, task_id, requested_at)"
                " VALUES (%s, %s, %s, %s, %s)",
                (
                    approval.id,
                    approval.model_dump_json(),
                    approval.status,
                    approval.task_id,
                    _as_utc_naive(approval.requested_at),
                ),
            )
        return approval.model_copy(deep=True)

    def get(self, approval_id: str) -> ApprovalRequest | None:
        with self._connect().cursor() as cursor:
            cursor.execute(
                "SELECT payload FROM approvals WHERE id = %s",
                (approval_id,),
            )
            row = cursor.fetchone()
        return ApprovalRequest.model_validate_json(row[0]) if row else None

    def update(self, approval: ApprovalRequest) -> ApprovalRequest:
        with self._connect().cursor() as cursor:
            cursor.execute(
                "UPDATE approvals SET payload = %s, status = %s,"
                " task_id = %s, requested_at = %s WHERE id = %s",
                (
                    approval.model_dump_json(),
                    approval.status,
                    approval.task_id,
                    _as_utc_naive(approval.requested_at),
                    approval.id,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(approval.id)
        return approval.model_copy(deep=True)

    def _query(self, where: str, params: tuple[Any, ...]) -> list[ApprovalRequest]:
        with self._connect().cursor() as cursor:
            cursor.execute(
                f"SELECT payload FROM approvals WHERE {where} ORDER BY requested_at, id",
                params,
            )
            rows = cursor.fetchall()
        return [ApprovalRequest.model_validate_json(row[0]) for row in rows]

    def list_by_task(self, task_id: str) -> list[ApprovalRequest]:
        return self._query("task_id = %s", (task_id,))

    def list_pending(self) -> list[ApprovalRequest]:
        return self._query("status = %s", ("PENDING",))

    def add_decision(self, decision: ApprovalDecision) -> None:
        with self._connect().cursor() as cursor:
            cursor.execute(
                "INSERT INTO decisions(approval_id, payload) VALUES (%s, %s)",
                (decision.approval_id, decision.model_dump_json()),
            )

    def list_decisions(self, approval_id: str) -> list[ApprovalDecision]:
        with self._connect().cursor() as cursor:
            cursor.execute(
                "SELECT payload FROM decisions WHERE approval_id = %s ORDER BY sequence",
                (approval_id,),
            )
            rows = cursor.fetchall()
        return [ApprovalDecision.model_validate_json(row[0]) for row in rows]


class MariaDbExecutionStore:
    """Workflow checkpoints and approvals in a MariaDB database.

    One connection per thread: run drives execute agent steps on a
    background thread while the API keeps serving reads on its request
    threads, and PyMySQL connections are not thread-safe.
    """

    def __init__(self, config: MariaDbConfig) -> None:
        if not _DATABASE_NAME.match(config.database):
            raise ValueError(
                f"Invalid MariaDB database name {config.database!r}:"
                " letters, digits and underscores only",
            )
        self._config = config
        self._local = threading.local()
        self._local.connection = self._open()
        self._migrate()
        self.approvals = MariaDbApprovalRepository(self._connection)
        self._max_allowed_packet = self._read_max_allowed_packet()
        self._packet_warned: set[str] = set()

    def _read_max_allowed_packet(self) -> int | None:
        try:
            with self._connection().cursor() as cursor:
                cursor.execute("SELECT @@max_allowed_packet")
                row = cursor.fetchone()
            return int(row[0]) if row else None
        except Exception:
            return None

    def _check_payload_size(self, run_id: str, payload: str) -> None:
        """Warns when one run's payload nears the server's packet cap.

        A single execution payload holds every artifact (including
        CODE text and test output) plus all observations and results,
        so a long run grows it monotonically; past max_allowed_packet
        the save itself fails. The structural fix is splitting
        observations and artifact history into append-only tables —
        proposed, not yet built (payloads stay the checkpoint format
        until then).
        """
        if self._max_allowed_packet is None or run_id in self._packet_warned:
            return
        size = len(payload.encode("utf-8"))
        if size > self._max_allowed_packet // 2:
            self._packet_warned.add(run_id)
            logger.warning(
                "Execution %s payload is %d bytes, over 50%% of the"
                " server's max_allowed_packet (%d): saves will fail"
                " outright at the cap. Consider splitting observations"
                " and artifact history out of the payload.",
                run_id,
                size,
                self._max_allowed_packet,
            )

    def _connection(self) -> Any:
        connection = getattr(self._local, "connection", None)
        if connection is not None and not getattr(
            self._local,
            "in_transaction",
            False,
        ):
            # A cached per-thread connection can be silently dead by
            # the time it is reused (server restart, wait_timeout).
            # ping(reconnect=True) revives it; if even that fails, drop
            # it and open a fresh one. Skipped inside a transaction: a
            # reconnect there would silently lose the transaction.
            try:
                connection.ping(reconnect=True)
            except Exception:
                with suppress(Exception):
                    connection.close()
                connection = None
        if connection is None:
            connection = self._connect(database=self._config.database)
            self._local.connection = connection
        return connection

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
        with self._connection().cursor() as cursor:
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
        connection = self._connection()
        connection.begin()
        # While a transaction is open the connection must not be
        # pinged/reconnected (see _connection); the block below always
        # ends it with commit or rollback, so the connection returns
        # to the pool of reusable connections in a clean state. If the
        # owning thread dies mid-transaction, the server rolls back
        # when the dropped connection is reaped.
        self._local.in_transaction = True
        try:
            yield
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            self._local.in_transaction = False

    def create_execution(self, run: WorkflowExecution) -> None:
        run.version = 0
        payload = run.model_dump_json()
        self._check_payload_size(run.id, payload)
        with self._connection().cursor() as cursor:
            cursor.execute(
                "INSERT INTO executions(id, project_id, payload, version,"
                " task_id, stage, status, workflow_id, started_at, updated_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    run.id,
                    run.project_id,
                    payload,
                    0,
                    *_execution_columns(run),
                ),
            )

    def save_execution(self, run: WorkflowExecution) -> None:
        # Optimistic locking, same contract as the SQLite store: the
        # update only lands on the row version this copy was read
        # from; a stale writer fails loudly instead of overwriting.
        expected = run.version
        run.version = expected + 1
        payload = run.model_dump_json()
        self._check_payload_size(run.id, payload)
        try:
            with self._connection().cursor() as cursor:
                cursor.execute(
                    "UPDATE executions SET payload = %s, version = %s,"
                    " task_id = %s, stage = %s, status = %s,"
                    " workflow_id = %s, started_at = %s, updated_at = %s"
                    " WHERE id = %s AND version = %s",
                    (
                        payload,
                        run.version,
                        *_execution_columns(run),
                        run.id,
                        expected,
                    ),
                )
                if cursor.rowcount != 1:
                    cursor.execute(
                        "SELECT 1 FROM executions WHERE id = %s",
                        (run.id,),
                    )
                    if cursor.fetchone() is None:
                        raise KeyError(run.id)
                    raise ConcurrentModificationError(
                        f"Execution '{run.id}' was modified concurrently"
                        f" (expected version {expected})",
                    )
        except BaseException:
            run.version = expected
            raise

    def get_execution(
        self,
        run_id: str,
        *,
        for_update: bool = False,
    ) -> WorkflowExecution:
        # FOR UPDATE (used by the orchestrator's claim phase) locks the
        # row until the claim transaction ends, so two processes cannot
        # both observe in_flight unset and claim the same run.
        suffix = " FOR UPDATE" if for_update else ""
        with self._connection().cursor() as cursor:
            cursor.execute(
                f"SELECT payload, version FROM executions WHERE id = %s{suffix}",
                (run_id,),
            )
            row = cursor.fetchone()
        if row is None:
            raise KeyError(run_id)
        run = WorkflowExecution.model_validate_json(row[0])
        run.version = row[1]
        return run

    def list_executions(self, project_id: str) -> list[WorkflowExecution]:
        with self._connection().cursor() as cursor:
            cursor.execute(
                "SELECT payload, version FROM executions WHERE project_id = %s ORDER BY id",
                (project_id,),
            )
            rows = cursor.fetchall()
        runs = []
        for payload, version in rows:
            run = WorkflowExecution.model_validate_json(payload)
            run.version = version
            runs.append(run)
        return runs

    def list_execution_summaries(
        self,
        project_id: str | None = None,
        *,
        status: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Metadata-column rows only: no payload is read or parsed."""
        clauses: list[str] = []
        params: list[Any] = []
        if project_id is not None:
            clauses.append("project_id = %s")
            params.append(project_id)
        if status is not None:
            clauses.append("status = %s")
            params.append(status)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = (
            "SELECT id, project_id, task_id, workflow_id, stage, status,"
            " started_at, updated_at FROM executions"
            f"{where} ORDER BY updated_at, id"
        )
        if limit is not None:
            sql += " LIMIT %s OFFSET %s"
            params.extend([limit, offset])
        elif offset:
            sql += " LIMIT 18446744073709551615 OFFSET %s"
            params.append(offset)
        with self._connection().cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
        return [
            {
                "id": row[0],
                "projectId": row[1],
                "taskId": row[2],
                "workflowId": row[3],
                "stage": row[4],
                "status": row[5],
                "startedAt": _as_utc_iso(row[6]),
                "updatedAt": _as_utc_iso(row[7]),
            }
            for row in rows
        ]

    def close(self) -> None:
        # Closes the calling thread's connection; per-thread connections
        # of other (daemon) threads end with the process.
        connection = getattr(self._local, "connection", None)
        if connection is not None:
            connection.close()
            self._local.connection = None
