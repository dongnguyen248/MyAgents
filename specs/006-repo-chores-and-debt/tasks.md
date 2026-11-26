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
