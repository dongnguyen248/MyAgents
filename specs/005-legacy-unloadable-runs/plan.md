# Implementation Plan: C1 — Legacy Unloadable Runs

**Branch**: `005-legacy-unloadable-runs` | **Date**: 2026-11-26 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/005-legacy-unloadable-runs/spec.md`

## Summary

Implement approach `(a)`: expose `loadable: false` + safe `reason` on unloadable run views, render `"Legacy run"` badge, gate Resume / Run again / Cancel on `loadable`, and fix the reproduced `409` internal error message leak on `retry` / `resume` / `cancel`. (Alternatives `(b)` migration and `(c)` archive remain temporarily rejected.)

## Technical Context

**Language/Version**: Python 3.12 (`src/asf/api/service/queries.py`, `commands.py`, schemas), TypeScript / React (`apps/dashboard/`)
**Testing**: `pytest` + dashboard `npm run build && npm test && npm run lint && npm run format:check`
**Dependencies**: Independent, recommended after `001-workflow-status-truthful` (S0). May also absorb `operatorActionsFor` / `TaskDetailPage` Cancel gating if S0 T005 chooses Option B.

## Constitution Check

- Security rule (generic client errors, no internal paths/stack traces in `409` responses) directly governs the `retry`/`resume`/`cancel` fix.
- Must pass all Python and Dashboard CI gates.

## Project Structure

```text
specs/005-legacy-unloadable-runs/
├── spec.md
├── plan.md
└── tasks.md
```
