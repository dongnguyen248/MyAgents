# S0 — Workflow status truthfulness

Trạng thái: [~] đã code, chưa push (branch `fix/workflow-status-truthful`, 8 commit `0ab369a..e38f7a7`).
Phụ thuộc: không. Chặn: S0b, PR 2a, C1.

## Problem

`_workflow_status` caught every engine exception and defaulted
non-COMPLETED runs to RUNNING, so terminal runs the engine could no
longer load showed phantom RUNNING in the workflow view, the Live
Map snapshot, and the run dropdown auto-select.

## Requirements

- Terminal stages answer from the run itself, before touching the
  engine.
- On engine failure for a non-terminal run, report UNKNOWN where
  RUNNING was previously fabricated; service-side derivations
  (PAUSED, AI_REVIEWING, ESCALATED, WAITING_RETRY) still apply.
- Log the failure once per (run, exception type), bounded seen-set.
- Waiting view for UNKNOWN claims no step and no suggested actions.
- Dashboard: UNKNOWN in the status union; badge resolution never
  throws on an unlisted status string.

## Known deviations (decided, no open decision)

- `operatorActionsFor` has no UNKNOWN case (falls through to
  Pause/Cancel → 409) and TaskDetailPage self-gates Cancel on
  "not terminal". Both belong to C1 (spec 001). The round-4 fix
  exists only on `backup/s0-round4` and is not part of S0.
- `_current_activity` phase stays stage-derived for UNKNOWN runs.
