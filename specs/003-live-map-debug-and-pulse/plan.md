# Implementation Plan: PR 1 — Live Map Debug Data & Rejected Pulse

**Branch**: `feat/map-debug-data`, `feat/map-rejected-pulse` | **Date**: 2026-11-26 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/003-live-map-debug-and-pulse/spec.md`

## Summary

Deliver PR 1a (`feat/map-debug-data`) and PR 1b (`feat/map-rejected-pulse`). Both branches are complete and reported green on gates, awaiting push/merge. PR 1b is a hard prerequisite for PR 2c in `004-live-map-phase2-board`, and PR 1 as a whole precedes PR 2a.

## Technical Context

**Language/Version**: Python 3.12 / TypeScript React
**Dependencies**: Should land after `002-driver-state` (S0b) in the `S0 -> S0b -> PR1 -> PR2a` sequence; PR 1b specifically blocks PR 2c (`004-live-map-phase2-board`).
**Local Clone Note**: `feat/map-debug-data` and `feat/map-rejected-pulse` were not found in this repo root clone during setup; status is preserved from owner handoff.

## Constitution Check

- All CI gates reported passed by owner.
- Do not push or create PRs until explicitly instructed by owner.

## Project Structure

```text
specs/003-live-map-debug-and-pulse/
├── spec.md
├── plan.md
└── tasks.md
```
