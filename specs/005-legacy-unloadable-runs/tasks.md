---
description: "Task tracking for C1 — Legacy Unloadable Runs"
---

# Tasks: C1 — Legacy Unloadable Runs
Nguồn: goals/asf-run-status-visibility-and-diagnostics/files/c1-legacy-runs-tasks.md

**Input**: Design documents from `/specs/005-legacy-unloadable-runs/`
**Dependencies**: Independent, recommended after `001-workflow-status-truthful` (S0). Selected approach: `(a)` (`loadable: false` + `reason`); `(b)` migration and `(c)` archive temporarily rejected.

## Phase 1: Backend View & 409 Fix

- [ ] T001 [US1] Add `loadable` boolean and safe `reason` to run view schema/serializer in `src/asf/api/`
- [ ] T002 [US2] Fix reproduced `409` internal error message leak on `retry`, `resume`, and `cancel` for unloadable runs
- [ ] T003 [US1] [US2] Add backend unit tests for `loadable: false` + `reason` and safe `409` responses

## Phase 2: Dashboard Badge & `loadable` Action Gating

- [ ] T004 [US1] Render `"Legacy run"` badge in dashboard when `loadable` is `false`
- [ ] T005 [US2] Disable Resume, Run again, and Cancel in dashboard based on `loadable` (not `status`)
- [ ] T006 [US2] Add dashboard unit tests for `"Legacy run"` badge and `loadable`-based action gating
- [ ] T007 Resolve known deviation deferred from S0 (`operatorActionsFor` `UNKNOWN` fallthrough -> Pause/Cancel -> 409 and `TaskDetailPage` self-gated Cancel button) and run full CI gates
