---
description: "Task tracking for PR 1 — Live Map Debug Data & Rejected Pulse"
---

# Tasks: PR 1 — Live Map Debug Data & Rejected Pulse

**Input**: Design documents from `/specs/003-live-map-debug-and-pulse/`
**Branches**: `feat/map-debug-data`, `feat/map-rejected-pulse` (unpushed; not present in local clone `E:\develops\JAVA\MyAgents`)
**Dependencies**: Follows `002-driver-state` (S0b) in delivery chain; blocks `004-live-map-phase2-board` (PR 2a; specifically PR 1b blocks PR 2c)

## Phase 1: Delivered Work (Implemented Locally, Gates Passed, Unpushed)

- [x] T001 [US1] Implement Live Map debug data on branch `feat/map-debug-data` and pass gates (per owner handoff)
- [x] T002 [US2] Implement rejected pulse handling on branch `feat/map-rejected-pulse` (PR 1b) and pass gates (per owner handoff)

## Phase 2: Release (Pending Push Command)

- [~] T003 Push and merge `feat/map-debug-data` (PR 1a) after S0b (`002-driver-state`)
- [~] T004 Push and merge `feat/map-rejected-pulse` (PR 1b) — MUST land before PR 2c (`004-live-map-phase2-board`)
