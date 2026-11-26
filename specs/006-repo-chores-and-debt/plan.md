# Implementation Plan: Repository Chores & Technical Debt

**Branch**: `006-repo-chores-and-debt` | **Date**: 2026-11-26 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/006-repo-chores-and-debt/spec.md`

## Summary

Track non-feature maintenance chores and verification debt cleanly in one place so they are not lost between feature PRs.

## Technical Context

**Areas**: `apps/dashboard/src/components/settings/AgentConnectionFields.tsx`, root `PR-DRAFT-*.md`, git remote `origin/sshpush`, `scratch/inspect_run_status.py`, `gitleaks`.
**Dependencies**: Independent of S0/S0b/PR1/PR2/C1 (except Chore 2 `PR-DRAFT-*.md` cleanup should wait until those PRs no longer need the drafts).

## Project Structure

```text
specs/006-repo-chores-and-debt/
├── spec.md
├── plan.md
└── tasks.md
```
