---
description: "Task tracking for S0 — Truthful Workflow Status"
---

# Tasks: S0 — Truthful Workflow Status

**Input**: Design documents from `/specs/001-workflow-status-truthful/`
**Branch**: `fix/workflow-status-truthful` (unpushed; not present in this repo root clone)
**Dependencies**: None (blocks `002-driver-state` / S0b, `004-live-map-phase2-board` / PR 2a; recommended before `005-legacy-unloadable-runs` / C1)

## Phase 1: Delivered Work (Implemented Locally, Unpushed)

- [x] T001 [US1] Implement `engine_status` fallback and return `UNKNOWN` instead of fabricated `RUNNING` (`0ab369a..e38f7a7` on `fix/workflow-status-truthful`)
- [x] T002 [US2] Make dashboard status badge defensive for `UNKNOWN` and unrecognized statuses (`0ab369a..e38f7a7` on `fix/workflow-status-truthful`)
- [x] T003 [US1] Add 12 backend unit tests for truthful workflow status (`0ab369a..e38f7a7` on `fix/workflow-status-truthful`)
- [x] T004 [US2] Add 3 dashboard unit tests for defensive status badge (`0ab369a..e38f7a7` on `fix/workflow-status-truthful`)

## Phase 2: Decided Scope & Release

- [x] T005 Keep round 4 commits (`a54847f`, `b7b207d`, `3c96f9b`) only on `backup/s0-round4`; defer known deviation (`operatorActionsFor` `UNKNOWN` fallthrough -> Pause/Cancel -> 409 and `TaskDetailPage` self-gated Cancel button) to C1 (`005-legacy-unloadable-runs`)
- [~] T006 Push `fix/workflow-status-truthful` and merge S0 into `master` (awaiting explicit owner push command)
