# C1 — Implementation plan

Nguồn: goals/asf-run-status-visibility-and-diagnostics/files/c1-legacy-runs-tasks.md

## Preconditions

- S0 (`fix/workflow-status-truthful`) merged: UNKNOWN status, the
  `engine_status` fallback, and the truthful waiting view are the
  base this builds on.
- Branch from updated master, per-file commits, no push or PR
  without Dong's order.

## Backend

- Derive loadability where status is derived: reuse the S0
  engine-status path so a run is unloadable exactly when the engine
  load fails; do not add a second load attempt with different
  semantics. Keep `queries.py` line-neutral under the ratchet by
  putting new derivation in a helper module if needed.
- Add `loadable` and `loadableReason` (name to confirm against the
  view contract) to the workflow view and task run entries.
  Reason text: short, operator-facing, no raw exception payload.
- Backend operator commands keep failing at engine load for direct
  API callers; C1 gates the dashboard, it does not add new command
  pre-checks unless the spec review asks for them.

## Dashboard

- Extend the workflow/task view types with the new fields.
- Render a "Legacy run" badge next to the status badge for
  `loadable: false`.
- Gate operator actions on `loadable`: `operatorActionsFor`
  returns no actions for unloadable runs regardless of status;
  TaskDetailPage's header buttons derive from the same rule
  instead of status checks. Reference `backup/s0-round4` for the
  UNKNOWN handling shape, rewritten onto the loadable gate.
- UNKNOWN keeps rendering through the S0 badge fallback.

## Tests

- Backend: unloadable terminal and non-terminal runs expose
  `loadable: false` + reason; loadable runs expose `true`;
  task and workflow views agree.
- Dashboard: operator actions empty for unloadable runs across
  statuses (UNKNOWN, FAILED, ESCALATED, PAUSED, WAITING_RETRY);
  loadable runs keep current actions; badge renders for
  unloadable runs (lib-level tests where the runner requires it).

## Gates

- `ruff check src tests`, `ruff format --check src tests harness`,
  `mypy src --platform linux`, `bandit -c .bandit -r src -q`,
  ratchet, `pytest -q`, demo selftest; dashboard `npm test`,
  `npm run build`, lint on touched files with Rule G counts
  before/after. Report master vs branch test counts.

## Risks

- View-contract change: JSON schema, Python models, dashboard TS
  types, and tests move together.
- Reason text must not leak internal exception detail; reuse the
  existing redaction path.
- Rollback: revert the commits; no data migration involved.
