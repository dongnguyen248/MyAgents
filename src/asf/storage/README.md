# Persistence and Storage Adapters (`src/asf/storage/`)

**Responsibility:** Persistence adapters for repositories across the platform.

## In-Memory Storage (`memory.py`)
Provides reference in-memory implementations of storage protocols:
- `InMemoryApprovalRepository`: In-memory implementation of `ApprovalRepository`. Stores and returns deep copies to guarantee isolation, sorts pending and task lists by `(requested_at, id)`, and maintains decisions per approval in insertion order. Updating an unknown ID raises `KeyError`.

## Persistent Storage Backends
Production storage backends (e.g., PostgreSQL, SQLite, Redis, or cloud storage) are implemented in later phases. Core engines and ports depend only on the protocols defined in contracts and ports modules.
