# Feature Specification: S0b — Driver State Reporting (`queued` / `driving` / `idle`)

**Feature Branch**: `[002-driver-state]` (not created yet)

**Created**: 2026-11-26

**Status**: Draft (Blocked — requires separate approval and S0 merged first)

**Input**: S0b "driver.state" (`queued` / `driving` / `idle`).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Expose Authoritative Driver State (Priority: P1)

Operators and downstream Live Map consumers can inspect whether the run driver is currently `queued`, `driving`, or `idle`, rather than inferring queue/execution state from workflow status alone.

**Why this priority**: Live Map Phase 2 (`004-live-map-phase2-board` / PR 2a) needs authoritative driver state to render empty/queued states such as `"queued behind the run pool"`.

**Independent Test**: Unit and API contract tests verifying `driver.state` transitions across `queued`, `driving`, and `idle`.

**Acceptance Scenarios**:

1. **Given** a run waiting in the run pool, **When** its driver state is queried, **Then** `driver.state` is `queued`.
2. **Given** a run actively driven by a worker, **When** its driver state is queried, **Then** `driver.state` is `driving`.
3. **Given** no active driving loop on the run, **When** its driver state is queried, **Then** `driver.state` is `idle`.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST expose `driver.state` with allowed values `queued`, `driving`, and `idle`.
- **FR-002**: Implementation MUST NOT start until S0 (`001-workflow-status-truthful`) is merged into `master` and separate owner approval is granted.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All three `driver.state` values (`queued`, `driving`, `idle`) are covered by deterministic unit tests and pass all CI gates.
