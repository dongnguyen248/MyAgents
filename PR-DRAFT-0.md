# fix(live-map): emit shell pulses sequentially, not in parallel

## What

`MapSandbox` no longer emits every command's start pulse up front.
Only the first command's start goes out before the batch runs; each
later start is emitted when the previous command's end is known,
stamped with that end's timestamp and the command's own measured
duration from its `CommandResult`. The emitted sequence is start,
end, start, end - at most one shell span is ever open, so the board
no longer shows a fake xN on the Shell station and the station clock
only runs while a command genuinely runs. On a raised error the
started command ends as an error and the remaining commands are
reported as start+blocked pairs at that moment. `_Reporter.end`
now returns the end timestamp and `_Reporter.start` accepts an
explicit start timestamp to make the chaining possible.

One new test pins the exact start/end sequence, the timestamp chain
(end of command N == start of command N+1, durations preserved) and
the never-more-than-one-open-span invariant.

## Why

SandboxPort takes the whole batch at once while the commands inside
run sequentially. Slice 2's wrapper emitted all starts immediately,
so the map displayed parallel shell calls that never happened.

## How

- `src/asf/tools/map_wrap.py` - `MapSandbox.run` starts only the
  first span; `_end_sequence` walks the aligned CommandResults,
  ending each span and starting the next at the previous end;
  `_end_failed` mirrors the same chaining on the exception path.
  Repository and transport wrappers are unchanged.

## Verification

- `ruff check src tests` - all checks passed.
- `ruff format --check src tests harness` - 438 files already formatted.
- `mypy src` - success, no issues in 183 source files.
- `pytest -q` - 2150 passed, 8 skipped, 425 subtests passed
  (2149 on master + 1 new).
- `python scripts/check_code_structure.py --baseline .code-structure-baseline.json` - 0 violations, 224 measured (baseline unchanged).
- `python -m asf.api.demo --selftest` - SELFTEST OK, final stage COMPLETED.
- Manual: not performed. On a live run with several test commands,
  the Shell station should never show x2+ and its clock should stop
  between commands.

## Risk & Rollback

- Security impact: none. Labels and payloads are unchanged; only
  pulse timing and ordering change.
- Two-way door: revert the merge, or run with `ASF_LIVE_MAP=0`
  (wrappers are not installed then, as before).
- Blast radius: `MapSandbox` pulse emission only. Wrapped results,
  exceptions and statuses are byte-identical to before; one existing
  behaviour note: a skipped command now gets a zero-duration span
  stamped at the previous command's end instead of a span opened at
  batch start.

## Context

- Resolves: None (direct request from the project owner, 2026-11-23;
  follow-up to Slice 2, PR #91).
- Relates to: Phase 2 of the live map follows in separate PRs
  (model-change rows, agent orbit dots, PR link, replay proposal).
- ADR/RFC: None.
