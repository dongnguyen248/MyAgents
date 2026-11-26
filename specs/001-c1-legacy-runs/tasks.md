Nguồn: goals/asf-run-status-visibility-and-diagnostics/files/c1-legacy-runs-tasks.md

# C1 — Legacy unloadable runs: tasks

Bản chính để theo dõi việc C1. Nội dung lấy từ file nguồn ở trên;
file nguồn là bản gốc, không sửa.

- [ ] Expose `loadable: false` + reason in workflow/task views for runs the engine cannot load.
  - [ ] Backend: derive loadability on the S0 engine-status path; add fields to workflow and task views.
  - [ ] Contract: JSON schema, Python models, dashboard TS types, tests move together.
- [ ] Show a "Legacy run" badge and disable actions that cannot work on unloadable runs.
  - [ ] Badge next to the status badge in workflow list, workflow detail, and task run list.
  - [ ] Gate every engine-loading operator action on `loadable`, not status alone.
- [ ] Tái áp dụng/viết lại fix operatorActions + TaskDetailPage, tham khảo backup/s0-round4 (commits a54847f, b7b207d, 3c96f9b — branch chỉ để tham khảo, không merge nguyên trạng; gate nút dựa trên loadable:false).
  - [ ] `operatorActionsFor`: no actions for unloadable runs, any status.
  - [ ] TaskDetailPage: header buttons derive from the same gate.
  - [ ] Tests: unloadable across statuses → no actions; loadable runs unchanged.
- [ ] Run full gates (backend + dashboard) and report master vs branch counts.
