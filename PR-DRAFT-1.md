# feat(live-map): model-change feed rows and station flash

## What

Phase 2, item 1 (dashboard only). When two consecutive model spans
of the same run use different models, the feed gains a ◆ row
`A → B` at the moment the new model starts, and the centre plus the
Model station flash for a few seconds.

- `modelChanges(board)` in `src/lib/mapBoard.ts` derives the
  switches from the run's own model entries (comparison is inside
  the run only - a board never holds another run's entries).
- `feedItems(board, filter)` merges pulse rows and change markers
  newest-first under the existing 16-line limit; on a timestamp tie
  the change marker sorts first. The agent filter applies to change
  markers too (they carry the agent of the span that switched).
- `isModelFlashing(board)` is true while the newest change is within
  4 s of the board's latest timestamp - the board's own timeline,
  not the wall clock, so a finished run's snapshot does not flash
  forever. The canvas adds an `lm-flash` CSS animation (0.8 s x 5)
  to the centre and the Model station.
- Three new board tests: change detection (repeat models do not
  count), feed interleaving, flash window.

## Why

With per-agent models and automatic routing, a run silently switches
models between agents; the operator had no way to see when or to
what.

## How

- `apps/dashboard/src/lib/mapBoard.ts` - `ModelChange`,
  `modelChanges`, `isModelFlashing`, `feedItems`.
- `apps/dashboard/src/components/livemap/MapFeed.tsx` - renders
  `FeedItem[]`; change markers are plain rows, not buttons.
- `apps/dashboard/src/components/livemap/MapCanvas.tsx` - flashing
  prop threaded to the model StationNode and CentreNode; small
  presentational extractions (StationSpoke, StationCircle,
  CentreCircle) keep every function within the lint line budget.
- `apps/dashboard/src/pages/LiveMap/LiveMapPage.tsx` - FeedCard now
  passes `feedItems(...)`.
- `apps/dashboard/src/styles/global.css` - `lm-flash` keyframes and
  the change-symbol colour (append-only).

## Verification

- `npm run build` - passed.
- `npm test` - 87 passed, 0 failed (84 on the base + 3 new).
- `npm run lint` - clean; `npm run format:check` - clean.
- Rule G: every touched dashboard file measures zero unsuppressed
  ESLint problems (they were zero before this change too).
- Backend untouched by this PR.
- Manual: not performed. On a run whose agents use different models
  (e.g. via muse2api aliases or per-agent overrides), the feed
  should show a ◆ row at each switch and the Model station should
  pulse briefly.

## Risk & Rollback

- Security impact: none. Model names were already shown as model
  pulse labels; no new data leaves the machine.
- Two-way door: revert the merge. No backend or contract change.
- Blast radius: the LiveMap feed and canvas only; other pages do
  not import the new helpers.

## Context

- Resolves: None (direct request from the project owner, 2026-11-23;
  Phase 2 of the live map).
- Relates to: PR #90 (Slice 1), PR #91 (Slice 2). This branch is
  stacked on `fix/map-shell-pulse-timing` - create the PR with that
  branch as base, or merge that PR first and retarget to master.
- ADR/RFC: None.
