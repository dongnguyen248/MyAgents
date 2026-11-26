---
description: "Task tracking for PR 2a/2b/2c — Live Map Phase 2"
---

# Tasks: PR 2a/2b/2c — Live Map Phase 2

**Input**: Design documents from `/specs/004-live-map-phase2-board/`
**Dependencies**: Blocked by `001-workflow-status-truthful` (S0), `002-driver-state` (S0b), and `003-live-map-debug-and-pulse` (PR 1; PR 1b specifically blocks PR 2c)

## Phase 1: Prerequisites

- [ ] T001 Confirm S0 (`001`), S0b (`002`), and PR 1 (`003`) are merged into `master`

## Phase 2: PR 2a — Snapshot Selection & Truthful Empty/Unknown States

- [ ] T002 [US1] Implement snapshot selector capping at 3 snapshots (`tracked+events` first, then `non-terminal` by stage)
- [ ] T003 [US1] Render `"Status unknown"` for runs with `UNKNOWN` status in Live Map UI
- [ ] T004 [US1] Add `"queued behind the run pool"` copy to Live Map empty state using `driver.state`
- [ ] T005 [US1] Add unit tests for snapshot ranking, `"Status unknown"`, and empty-state copy; run dashboard + Python gates

## Phase 3: PR 2b & PR 2c — Remaining Live Map Phase 2 Slices

- [ ] T006 [US2] Implement PR 2b Live Map enhancements and pass gates
- [ ] T007 [US2] Confirm PR 1b (`feat/map-rejected-pulse` in `003`) is merged, then implement PR 2c and pass gates
