# Feature Specification: C1 — Legacy Unloadable Runs

**Feature Branch**: `[005-legacy-unloadable-runs]` (not created yet)

**Created**: 2026-11-26

**Status**: Draft (Proposed approach `(a)`; independent, recommended after S0 `001-workflow-status-truthful`)

**Input**: C1 "run legacy không load được".

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Surface `loadable: false` and `"Legacy run"` Badge (Priority: P1)

When an existing/legacy run cannot be loaded by the current runtime/schema, the API view explicitly marks `loadable: false` with a safe `reason`, and the dashboard renders a `"Legacy run"` badge instead of failing or misleading the operator.

**Why this priority**: Operators currently see broken actions on legacy runs because the UI only inspects `status` and assumes the run is loadable.

**Independent Test**: Backend API serialization test for `loadable: false` + `reason`, plus dashboard badge rendering test for `"Legacy run"`.

**Acceptance Scenarios**:

1. **Given** a legacy run that cannot be loaded, **When** the run view is returned by the API, **Then** it includes `loadable: false` and a human-safe `reason`.
2. **Given** a run view with `loadable: false`, **When** the dashboard renders the run row/header, **Then** it displays the `"Legacy run"` badge.

---

### User Story 2 - Gate Actions by `loadable` & Fix 409 Internal Message Leak (Priority: P1)

The dashboard disables **Resume**, **Run again**, and **Cancel** based on `loadable === false` (not `status`), and backend `retry` / `resume` / `cancel` endpoints reject unloadable runs cleanly without leaking internal error messages in HTTP `409` responses.

**Why this priority**: Reproduced bug — calling `retry`, `resume`, or `cancel` on an unloadable run currently returns `409` with an internal message.

**Independent Test**: Backend tests for `retry`/`resume`/`cancel` on unloadable runs returning generic safe error responses, plus dashboard tests verifying Resume/Run again/Cancel disabled when `loadable: false`.

**Acceptance Scenarios**:

1. **Given** a run with `loadable: false`, **When** rendered in the dashboard, **Then** Resume, Run again, and Cancel controls are disabled regardless of `status`.
2. **Given** an unloadable run, **When** `retry`, `resume`, or `cancel` is invoked via API, **Then** the server returns a safe generic `409` (no internal exception/path details).

## Alternatives Considered (Temporarily Rejected)

- **Option (b) Migration**: Migrating legacy run records in-place — temporarily rejected due to schema/data risk and complexity.
- **Option (c) Archive**: Moving/hiding legacy runs into an archive — temporarily rejected because operators still need visibility into historical runs.
- **Selected Option (a)**: Non-destructive view annotation (`loadable: false` + `reason`) + `"Legacy run"` badge + `loadable`-based action gating.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Run view payload MUST include `loadable: boolean` and `reason` when `loadable` is `false`.
- **FR-002**: Dashboard MUST render `"Legacy run"` badge when `loadable` is `false`.
- **FR-003**: Dashboard MUST disable Resume, Run again, and Cancel based on `loadable`, not `status`.
- **FR-004**: Backend `retry`, `resume`, and `cancel` on an unloadable run MUST NOT expose internal error messages in HTTP `409` responses.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Reproduced `409` internal-message bug on `retry`/`resume`/`cancel` is eliminated and covered by regression tests.
- **SC-002**: Dashboard action gating (`loadable: false`) and `"Legacy run"` badge pass `npm test`, `npm run lint`, `npm run build`, and Python CI gates.
