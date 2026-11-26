# Implementation Plan: S0 — Truthful Workflow Status

**Branch**: `fix/workflow-status-truthful` | **Date**: 2026-11-26 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-workflow-status-truthful/spec.md`

## Summary

Replace fabricated `RUNNING` workflow status fallback with `engine_status` fallback / `UNKNOWN` on the backend, and add defensive status badge rendering on the dashboard. Core work is implemented across 8 commits (`0ab369a..e38f7a7`); awaiting owner decision on 3 round-4 commits (`a54847f`, `b7b207d`, `3c96f9b`) and push authorization.

## Technical Context

**Language/Version**: Python 3.12 (`src/asf/api/`), TypeScript / React (`apps/dashboard/`)
**Testing**: `pytest` (12 backend tests), Vitest / dashboard `npm test` (3 dashboard tests)
**Constraints**: Must not break existing workflow status consumers; must pass Python + Dashboard CI gates before push.
**Dependencies**: Upstream prerequisite for `002-driver-state` (S0b), `004-live-map-phase2-board` (PR 2a), and recommended before `005-legacy-unloadable-runs` (C1).

## Constitution Check

- Code structure & security gates apply to `fix/workflow-status-truthful` before merge.
- Branch safety: do not reset, rebase, amend, or push `fix/workflow-status-truthful` without explicit owner instruction.
- Local clone note: `fix/workflow-status-truthful` was not found in `E:\develops\JAVA\MyAgents` during setup; commit hashes (`0ab369a..e38f7a7`, `a54847f`, `b7b207d`, `3c96f9b`) are preserved from owner handoff.

## Project Structure

```text
specs/001-workflow-status-truthful/
├── spec.md
├── plan.md
└── tasks.md
```

**Structure Decision**: Existing backend API service and dashboard status badge components; no new top-level packages.
