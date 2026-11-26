# Feature Specification: PR 1 — Live Map Debug Data & Rejected Pulse

**Feature Branches**: `feat/map-debug-data` (PR 1a), `feat/map-rejected-pulse` (PR 1b) — both unpushed (branches not present in this repo root clone; status recorded from owner handoff)

**Created**: 2026-11-26

**Status**: Implemented & Gates Passed (Unpushed — awaiting push command)

**Input**: PR 1 map debug (`feat/map-debug-data` and `feat/map-rejected-pulse`).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Map Debug Data (`feat/map-debug-data`, PR 1a) (Priority: P1)

Operators and developers can inspect Live Map debug data cleanly without breaking existing map board rendering.

**Independent Test**: Verified by CI gates on `feat/map-debug-data` (reported passed by owner).

---

### User Story 2 - Rejected Pulse Visualization (`feat/map-rejected-pulse`, PR 1b) (Priority: P1)

Rejected pulses are surfaced accurately in Live Map telemetry/UI, providing the prerequisite signal needed by PR 2c (`004-live-map-phase2-board`).

**Independent Test**: Verified by CI gates on `feat/map-rejected-pulse` (reported passed by owner).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `feat/map-debug-data` exposes Live Map debug data and passes all repository gates.
- **FR-002**: `feat/map-rejected-pulse` (PR 1b) handles rejected pulse events and MUST merge before PR 2c (`004-live-map-phase2-board`).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Both `feat/map-debug-data` and `feat/map-rejected-pulse` pass all repository gates (reported passed by owner; branches not present locally to re-run).
