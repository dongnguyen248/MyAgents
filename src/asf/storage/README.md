# Persistence and Storage Adapters (`src/asf/storage/`)

**Responsibility:** Persistence adapters for repositories across the platform.

## In-Memory Storage (`memory.py`)
Provides reference in-memory implementations of storage protocols:
- `InMemoryApprovalRepository`: In-memory implementation of `ApprovalRepository`. Stores and returns deep copies to guarantee isolation, sorts pending and task lists by `(requested_at, id)`, and maintains decisions per approval in insertion order. Updating an unknown ID raises `KeyError`.

## Local SQLite (`sqlite.py`)

`SQLiteExecutionStore` implements the orchestration `ExecutionStore` protocol
using Python's standard-library sqlite3. It stores complete execution checkpoints
(including artifacts, results, retry deadlines, task-item progress and observation
outbox) and exposes `SQLiteApprovalRepository` through `store.approvals`.

The orchestrator uses the same connection/transaction for approval decisions,
approval creation and the corresponding execution checkpoint. A separate committed
in-flight checkpoint precedes agent/action dispatch; an interrupted dispatch is
never replayed without explicit operator recovery.

Use a private local path under the ignored `artifacts` directory, whose parent
must already exist. Call `close()` when finished. Do not pass credentials in
execution input/context; this database retains original application content and
is NOT a redacted evidence log or an encrypted secret store.

Scope: one local synchronous worker, not a distributed/production storage claim.
SQLite holds a write transaction during dispatch finalization, including the
agent call; concurrent writers may receive SQLITE_BUSY. There is no lease-based
multi-worker scheduler, automatic migration or cross-service transaction.
Low-level approval operations used independently of the orchestrator must be
wrapped in `store.transaction()` to obtain multi-operation atomicity.

WorkflowRun and Task are schema-validated projections from checkpoints, not new
implementations of every standalone CRUD repository listed in `contracts/ports.md`.
