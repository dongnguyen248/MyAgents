# Implementation Plan: S0b — Driver State Reporting

**Branch**: `002-driver-state` | **Date**: 2026-11-26 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-driver-state/spec.md`

## Summary

Expose `driver.state` (`queued`, `driving`, `idle`) cleanly on top of S0 (`001-workflow-status-truthful`) so Live Map Phase 2 can distinguish queued runs from active or idle runs.

## Technical Context

**Language/Version**: Python 3.12 (`src/asf/api/service/driver.py`, API schemas)
**Testing**: `pytest` + `mypy src` + `ruff check` + `bandit` + `check_code_structure.py`
**Dependencies**: Depends on `001-workflow-status-truthful` (S0) merged; blocks `004-live-map-phase2-board` (PR 2a).

## Constitution Check

- Must pass all Python CI gates and `check_code_structure.py` ratchet.
- Requires explicit separate approval from owner before implementation begins.

## Project Structure

```text
specs/002-driver-state/
├── spec.md
├── plan.md
└── tasks.md
```
