# Feature Specification: S0 — Truthful Workflow Status

**Feature Branch**: `fix/workflow-status-truthful` (unpushed; 8 commits `0ab369a..e38f7a7` per owner handoff — branch not present in local clone `E:\develops\JAVA\MyAgents`)

**Created**: 2026-11-26

**Status**: Implemented (Unpushed — awaiting owner decision on round 4 commits and push command)

**Input**: S0 "workflow status trung thực" — eliminate fabricated `RUNNING` status fallback, surface `UNKNOWN` honestly, and make dashboard status badges defensive.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Truthful Workflow Status on Backend (Priority: P1)

When the backend cannot resolve an authoritative workflow status from the engine/store, it reports `UNKNOWN` via `engine_status` fallback rather than fabricating `RUNNING`.

**Why this priority**: Fabricated `RUNNING` statuses mislead operators and downstream Live Map views into treating stalled, unreadable, or unknown runs as actively executing.

**Independent Test**: Verified by 12 backend unit tests covering `engine_status` fallback and `UNKNOWN` mapping.

**Acceptance Scenarios**:

1. **Given** a run whose authoritative workflow status cannot be resolved, **When** the API formats the run status, **Then** it falls back to `engine_status` or `UNKNOWN` instead of fabricating `RUNNING`.

---

### User Story 2 - Defensive Dashboard Status Badge (Priority: P1)

The dashboard renders `UNKNOWN` (and unexpected/missing status values) safely with a defensive badge rather than crashing or displaying a misleading active-running indicator.

**Why this priority**: Frontend must stay consistent with the new `UNKNOWN` backend state.

**Independent Test**: Verified by 3 dashboard unit tests covering defensive badge rendering.

**Acceptance Scenarios**:

1. **Given** a run payload with `UNKNOWN` or unrecognized status, **When** the dashboard badge component renders, **Then** it displays a safe fallback badge without throwing or showing `RUNNING`.

---

### Edge Cases & Open Decisions

- **Operator action gating on `UNKNOWN`**: `operatorActionsFor` does not yet handle `UNKNOWN` (falls through to Pause/Cancel, which returns `409`), and `TaskDetailPage` gates the Cancel button itself.
- **Round 4 commits (`a54847f`, `b7b207d`, `3c96f9b`)**: [NEEDS DECISION] Three round 4 commits modified this area, but owner confirmation is pending on whether to:
  - **Option A**: Keep `a54847f`, `b7b207d`, `3c96f9b` inside S0 (`fix/workflow-status-truthful`).
  - **Option B**: Revert those 3 commits from S0 and defer operator action / Cancel gating for `UNKNOWN` & unloadable runs to C1 (`005-legacy-unloadable-runs`).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Backend status resolution MUST use `engine_status` fallback and return `UNKNOWN` instead of fabricating `RUNNING`.
- **FR-002**: Dashboard status badge MUST render `UNKNOWN` and unrecognized statuses defensively.
- **FR-003**: [NEEDS DECISION] `operatorActionsFor` handling of `UNKNOWN` and `TaskDetailPage` Cancel gating: keep round 4 commits (`a54847f`, `b7b207d`, `3c96f9b`) in S0 or revert and move to C1 (`005-legacy-unloadable-runs`).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 12 backend unit tests pass on `fix/workflow-status-truthful` (reported by owner; branch not present locally to re-run).
- **SC-002**: 3 dashboard unit tests pass on `fix/workflow-status-truthful` (reported by owner; branch not present locally to re-run).
- **SC-003**: No fabricated `RUNNING` status is emitted when engine status is unknown.
