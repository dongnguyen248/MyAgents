# Feature Specification: PR 2a/2b/2c — Live Map Phase 2 Board & Snapshot Selection

**Feature Branch**: `[004-live-map-phase2-board]` (not created yet)

**Created**: 2026-11-26

**Status**: Draft (Blocked — depends on S0, S0b, and PR 1 merged; PR 2c depends on PR 1b)

**Input**: PR 2a/2b/2c Live Map.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - PR 2a Snapshot Selection & Truthful States (Priority: P1)

Live Map selects at most 3 run snapshots, prioritizing runs that have `tracked+events` first, then `non-terminal` runs ordered by stage. Runs with `UNKNOWN` status display `"Status unknown"`, and the empty-state message includes `"queued behind the run pool"`.

**Why this priority**: Gives operators an immediate, truthful multi-run overview without misleading `RUNNING` labels when a run is unknown or queued.

**Independent Test**: Unit tests for snapshot selection ranking (max 3, `tracked+events` before `non-terminal` by stage), `"Status unknown"` label, and `"queued behind the run pool"` empty-state copy.

**Acceptance Scenarios**:

1. **Given** more than 3 candidate runs, **When** Live Map selects snapshots for display, **Then** it selects at most 3, placing `tracked+events` runs first followed by `non-terminal` runs ordered by stage.
2. **Given** a run with status `UNKNOWN`, **When** rendered in Live Map, **Then** it displays `"Status unknown"`.
3. **Given** no active driving snapshots while runs are queued, **When** Live Map renders its empty state, **Then** it includes `"queued behind the run pool"`.

---

### User Story 2 - PR 2b & PR 2c Follow-up Live Map Increments (Priority: P2)

Deliver remaining Live Map Phase 2 increments (2b and 2c), with PR 2c consuming the rejected-pulse support from PR 1b (`003-live-map-debug-and-pulse`).

**Independent Test**: Dashboard/backend tests per slice 2b and 2c.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: PR 2a MUST select at most 3 snapshots (`tracked+events` first, then `non-terminal` by stage).
- **FR-002**: PR 2a MUST display `"Status unknown"` for `UNKNOWN` workflow status.
- **FR-003**: PR 2a empty-state MUST include `"queued behind the run pool"`.
- **FR-004**: PR 2a MUST NOT start before S0 (`001`), S0b (`002`), and PR 1 (`003`) are merged; PR 2c MUST NOT start before PR 1b (`003`) is merged.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Snapshot selector returns <= 3 items with deterministic priority order in unit tests.
- **SC-002**: `"Status unknown"` and `"queued behind the run pool"` UI states are verified by dashboard tests and pass `npm run build`, `npm test`, `npm run lint`, and `npm run format:check`.
