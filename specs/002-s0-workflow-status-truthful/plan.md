# S0 — Plan (as implemented)

- `service/status_fallback.py`: `engine_status` wrapper returning
  UNKNOWN on failure, log-once with a 1024-entry bounded seen-set,
  `waiting_fallthrough` helper. Keeps `queries.py` line-neutral
  (file-lines 1229 → 1227).
- `queries.py`: terminal short-circuit; UNKNOWN only where RUNNING
  was fabricated.
- Dashboard: `types/workflow.ts` UNKNOWN union,
  `lib/workflowStatus.ts` defensive badge resolver,
  `WorkflowStatusBadge` delegates to it.
- Tests: 12 backend (`test_workflow_status_truthful.py`), 3
  dashboard (`workflowStatus.test.ts`). Gates: pytest 2236 passed,
  dashboard 96 passed.
- Delivery: Dong pushes and creates/merges the PR himself; draft at
  `PR-DRAFT-S0.md` (uncommitted in the worktree).
