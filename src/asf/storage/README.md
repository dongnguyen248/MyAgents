# Persistence and Storage Adapters (`src/asf/storage/`)

**Responsibility:** Persistence adapters for repositories across the platform.

There are exactly two execution stores. **MariaDB is the only store
for real runs**; the in-memory store exists for tests and explicitly
ephemeral demos, and loses everything when the process stops.

## MariaDB (`mariadb.py`)

`MariaDbExecutionStore` implements the orchestration `ExecutionStore`
protocol over a MariaDB server (via PyMySQL, imported lazily —
`pip install 'ai-software-agents[mariadb]'`). It stores complete
execution checkpoints (artifacts, results, retry deadlines, task-item
progress, observation outbox) and exposes `MariaDbApprovalRepository`
through `store.approvals`, so approval decisions, approval creation
and the corresponding execution checkpoint commit in ONE transaction
on one connection. A separate committed in-flight checkpoint precedes
agent/action dispatch; an interrupted dispatch is never replayed
without explicit operator recovery. Saves are version-guarded
(optimistic locking): a stale writer fails with
`ConcurrentModificationError` instead of overwriting newer state.

Opening the store creates the database when missing and applies
pending schema migrations recorded in `schema_migrations`, so the
only manual setup is an account with privileges on the application
database (`GRANT ALL PRIVILEGES ON asf.* TO ...`). Connection
settings come from the `ASF_MARIADB_HOST` / `ASF_MARIADB_PORT` /
`ASF_MARIADB_USER` / `ASF_MARIADB_PASSWORD` / `ASF_MARIADB_DATABASE`
environment variables (see `.env.example`). The API demo builds this
store by default; without `ASF_MARIADB_PASSWORD` it refuses to start
and prints setup guidance, unless `--ephemeral` is passed.

Low-level approval operations used independently of the orchestrator
must be wrapped in `store.transaction()` to obtain multi-operation
atomicity. Do not pass credentials in execution input/context; the
database retains original application content and is NOT a redacted
evidence log or an encrypted secret store.

WorkflowRun and Task are schema-validated projections from
checkpoints, not new implementations of every standalone CRUD
repository listed in `contracts/ports.md`.

## In-Memory Storage (`memory.py`)

Reference in-memory implementations of the storage protocols:

- `InMemoryApprovalRepository`: in-memory `ApprovalRepository`.
  Stores and returns deep copies to guarantee isolation, sorts
  pending and task lists by `(requested_at, id)`, and maintains
  decisions per approval in insertion order. Updating an unknown ID
  raises `KeyError`.
- `InMemoryStore`: an `ExecutionStore` that mirrors the MariaDB
  store's contract — create resets the version and refuses duplicate
  ids, saves are version-guarded, and `transaction()` snapshots
  executions AND approval decisions so both roll back together. It
  persists nothing: tests and `--ephemeral` demos only.

## Running the MariaDB integration tests

The store's real-server tests live in
`tests/integration/test_mariadb_store.py` and skip unless
`ASF_TEST_MARIADB=1`. With Docker:

```bash
docker run -d --name asf-mariadb -p 3306:3306 \
  -e MARIADB_ROOT_PASSWORD=rootpw mariadb:10.11
docker exec asf-mariadb mariadb -uroot -prootpw -e \
  "CREATE USER 'asf'@'%' IDENTIFIED BY 'asf-test-pw';
   GRANT ALL PRIVILEGES ON asf_test.* TO 'asf'@'%';"
ASF_TEST_MARIADB=1 ASF_MARIADB_PASSWORD=asf-test-pw \
  pytest tests/integration/test_mariadb_store.py
```

The tests use the `asf_test` database (override with
`ASF_TEST_MARIADB_DATABASE`) so a development database is never
touched; the store creates the database and tables itself.
