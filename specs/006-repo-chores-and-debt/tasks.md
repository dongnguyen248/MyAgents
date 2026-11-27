---
description: "Task tracking for Repository Chores & Technical Debt"
---

# Tasks: Repository Chores & Technical Debt

**Input**: Design documents from `/specs/006-repo-chores-and-debt/`
**Dependencies**: Independent maintenance items

## Chores & Debt

- [ ] T001 Refactor `ConnectionKeyField` in `apps/dashboard/src/components/settings/AgentConnectionFields.tsx` (40 lines -> <= 30 lines) and run `npm run lint && npm test && npm run build`
- [!] T002 [NEEDS DECISION] Decide whether to remove tracked `PR-DRAFT-0.md`, `PR-DRAFT-1.md`, `PR-DRAFT-2.md` from `master` (commits `8b12eb6`, `5817f1f`) after corresponding PRs land
- [ ] T003 Re-check `origin/sshpush` connectivity when proxy is stable
- [ ] T004 Locate/run `scratch/inspect_run_status.py` against real DB on Windows (never run yet; currently absent from `scratch/` in this clone)
- [ ] T005 Run `gitleaks git --redact .` in an environment where `gitleaks` is installed (blocked in sandbox previously)
- [!] T006 [NEEDS DECISION] chore/speckit-setup-sandbox (archive/speckit-setup-sandbox 5cfbecf): bản sandbox của speckit setup xung đột add/add với master ở .specify/memory/constitution.md và docs/speckit-workflow.md. Giữ bản master hay mang phần nào của sandbox sang.
- [ ] T007 Phát lại JSONL cho Live Map (archive/map-replay 1250579; origin/feat/map-pr-link b71e6ec): dev lại trên mã map hiện tại; xung đột ở apps/dashboard/src/styles/global.css, src/asf/api/service/map_hub.py, src/asf/api/service/map_publisher.py. Không đặt số spec 008 (đã bị 008-live-map-visual-polish dùng).
- [ ] T008 Hoàn tất T007 của specs/005-legacy-unloadable-runs bằng archive/s0-round4 (a54847f, b7b207d, 3c96f9b làm xong phần frontend: operatorActions.ts, TaskDetailPage.tsx; thiếu gate theo loadable false ở backend).
