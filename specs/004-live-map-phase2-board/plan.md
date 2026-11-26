# Implementation Plan: PR 2a/2b/2c — Live Map Phase 2

**Branch**: `004-live-map-phase2-board` | **Date**: 2026-11-26 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/004-live-map-phase2-board/spec.md`

## Summary

Implement Live Map Phase 2 in three increments (PR 2a, 2b, 2c), starting with PR 2a snapshot selection (max 3: `tracked+events` then `non-terminal` by stage), `"Status unknown"` display for `UNKNOWN`, and `"queued behind the run pool"` empty-state messaging.

## Technical Context

**Language/Version**: Python 3.12 (snapshot/API if needed), TypeScript / React (`apps/dashboard/src/lib/mapBoard.ts`, `apps/dashboard/src/pages/LiveMap/`, `apps/dashboard/src/components/livemap/`)
**Testing**: `pytest` + dashboard `npm run build && npm test && npm run lint && npm run format:check`
**Dependencies**: Blocked by S0 (`001`), S0b (`002`), PR 1 (`003`) merged; PR 2c specifically blocked by PR 1b (`003`).

## Constitution Check

- Respect ESLint function line limit (<= 30 lines) and brace rules in TypeScript.
- Must pass all Python and Dashboard CI gates.

## Project Structure

```text
specs/004-live-map-phase2-board/
├── spec.md
├── plan.md
└── tasks.md
```
