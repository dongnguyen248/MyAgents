# Feature Specification: Repository Chores & Technical Debt

**Feature Branch**: `[006-repo-chores-and-debt]` (tracking spec only)

**Created**: 2026-11-26

**Status**: Open Backlog

**Input**: Known chores and technical debt items from current repository state.

## Tracked Items

### Chore 1 - Dashboard Lint Violation in `AgentConnectionFields.tsx` (Priority: P2)
- `ConnectionKeyField` in `apps/dashboard/src/components/settings/AgentConnectionFields.tsx` is 40 lines (> 30-line function limit). Split helper/subcomponent to satisfy ESLint without suppressions.

### Chore 2 - Tracked `PR-DRAFT-*.md` Files on `master` (Priority: P3)
- `PR-DRAFT-0.md`, `PR-DRAFT-1.md`, and `PR-DRAFT-2.md` are currently tracked on `master` (commits `8b12eb6`, `5817f1f`). Decide whether to remove them from git tracking (`git rm`) once PRs are merged.

### Chore 3 - Re-check `origin/sshpush` Connectivity (Priority: P3)
- Re-check `origin/sshpush` remote/push path once proxy connectivity is stable.

### Chore 4 - Run `scratch/inspect_run_status.py` Against Real Windows DB (Priority: P2)
- `scratch/inspect_run_status.py` has never been executed against a real DB on Windows (note: file is not present in `repo root/scratch/` on this clone). Locate/restore script if needed and run read-only inspection on Windows DB.

### Chore 5 - Run `gitleaks` Secrets Scan Locally (Priority: P2)
- `gitleaks git --redact .` could not run in the sandbox environment. Run in an environment with `gitleaks` v8.30.1+ installed (CI runs it on Ubuntu).
