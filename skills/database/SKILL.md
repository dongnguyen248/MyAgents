---
name: database
description: Relational data design and access discipline — model constraints in the schema, write migrations that are safe to run and roll back, avoid N+1 queries and unbounded result sets, use transactions around multi-step writes, and parameterize every query. Applies when planning data changes, implementing persistence, reviewing data-access code, or fixing data bugs.
---

# Database discipline

## Schema design

- Let the schema enforce the invariants: NOT NULL by default,
  UNIQUE where the domain says unique, foreign keys for
  relationships, CHECK constraints for simple value rules. An
  invariant enforced only in application code will eventually be
  violated by a second writer.
- Every table gets a stable primary key; natural keys that can
  change (emails, usernames) are unique columns, not keys.
- Choose types that match the data: timestamps with timezone for
  instants, exact decimals for money (never float), enums or
  lookup tables for closed sets.
- Index for the queries the system actually runs — foreign keys
  and frequent filter/sort columns — and say which query each new
  index serves. Indexes are not free: each one taxes every write.

## Migrations

- Schema changes ship as migrations, never as manual steps:
  ordered, repeatable, and each either fully applies or not at all.
- Prefer backward-compatible steps for anything deployed while old
  code still runs: add nullable/new columns first, backfill, then
  enforce; drop columns only after no code reads them.
- A migration that destroys data says so loudly and is separate
  from structural changes. Large backfills run in bounded batches,
  not one unbounded UPDATE.

## Access patterns

- Parameterize every query — string-built SQL with interpolated
  values is an injection vulnerability, full stop (see the
  security skill).
- Never load a whole table to filter in memory; push selection,
  sorting and pagination to the database, and paginate every list
  that can grow (bounded page size, stable ordering).
- Avoid N+1: fetch associations in bulk (join or batched IN)
  instead of one query per row.
- Wrap multi-statement writes in one transaction; keep transactions
  short and never hold one open across user think-time or external
  calls. Read your own consistency requirements: use explicit
  isolation or locking where concurrent writers can interleave.
- Handle the database's failure modes in code: constraint
  violations, deadlocks and connection loss are normal events with
  defined behaviour (retry where idempotent, a clear error where
  not), not crashes.
