# C1 — Legacy unloadable runs

Nguồn: goals/asf-run-status-visibility-and-diagnostics/files/c1-legacy-runs-tasks.md

Trạng thái: [ ] đề xuất, chưa duyệt triển khai.
Phụ thuộc: S0 (002) đã merge; ngoài ra độc lập với S0b và chuỗi Live Map.

## Problem

Some stored runs can no longer be loaded by the engine: their stored
workflow definition or execution policy differs from the current one
(`engine._load` raises `ValueError`). After S0 these runs report a
truthful status (terminal stage, or UNKNOWN), but the views do not
say the run is unloadable, and operator actions that re-enter the
engine (Resume, Run again, Cancel, Pause, escalation actions) fail
with a 409 carrying the internal load message. Two dashboard gates
make this visible today: `operatorActionsFor` has no UNKNOWN case,
so UNKNOWN falls through to Pause/Cancel; TaskDetailPage self-gates
its Cancel button on "not terminal". Both dead-end at the same 409.

## Scope (option a only)

- Expose `loadable: false` plus a reason in the workflow and task
  views for runs the engine cannot load.
- Show a "Legacy run" badge for unloadable runs.
- Disable or hide operator actions that cannot work on unloadable
  runs. Dashboard button gating keys on `loadable: false` from the
  view, not on status alone, because service-derived statuses
  (ESCALATED, PAUSED, WAITING_RETRY, FAILED) on unloadable runs also
  produce dead-end actions.
- Re-apply or rewrite the operatorActions + TaskDetailPage fix,
  referencing branch `backup/s0-round4` (commits a54847f, b7b207d,
  3c96f9b) as reference only, not merged as-is.

## Out of scope

- Option (b): a migration rewriting stored definition/settings of
  terminal runs. Later, per-run, with backup and Dong's approval;
  it rewrites history.
- Option (c): an archive flag hiding unloadable runs. Rejected: it
  hides the problem.
- Any change to run execution, driving, or adoption semantics.
  Unloadable runs are already not driven or adopted after S0.

## Requirements

1. The workflow view and the task view's run entries carry
   `loadable` (boolean) and, when false, a human-readable reason
   that does not expose internal exception text beyond what the
   existing redacting pipeline allows.
2. Loadable runs are unchanged: `loadable: true`, no badge, all
   current actions behave as today.
3. An unloadable run shows a "Legacy run" badge wherever its status
   badge renders (workflow list, workflow detail, task run list).
4. No operator action that requires loading the run is offered for
   an unloadable run: Pause, Cancel, Continue, Resume from failure,
   Run again, escalation resume/fail, recover, restart driver.
5. Status rendering is unchanged from S0: terminal stages report
   themselves; non-terminal unloadable runs report UNKNOWN unless a
   service-side derivation applies.

## Acceptance criteria

- A stored run with a legacy definition shows `loadable: false`
  with a reason in both views, the Legacy badge, and no operator
  actions.
- A loadable run's views and actions are byte-identical to today
  apart from the added `loadable: true` field.
- Backend and dashboard tests cover loadable and unloadable runs,
  including UNKNOWN and service-derived statuses on unloadable
  runs.
- No stored data is rewritten; rollback is a plain revert.
