# feat(live-map): orbit dots for parallel agent executions

## What

Phase 2, item 2 (dashboard only). Every agent execution in flight
is now a small dot orbiting the Agents station, filled with that
agent's colour. Parallel executions show as multiple dots, staggered
by 60 degrees, one full turn per 7 seconds. A dot disappears as soon
as its execution's span ends, because the list is derived from the
board's running agent entries on every render.

- `runningAgents(board)` in `src/lib/mapBoard.ts` returns one
  `{spanId, agentId, color}` per running agent entry.
- `MapCanvas` renders `AgentOrbits`/`OrbitDot` (SMIL rotate) inside
  the Agents station node at radius 27 - outside the station circle
  and the Slice 2 clock ring.
- One new board test: two running executions listed with their agent
  colours, a finished execution excluded, model spans excluded.

## Why

The lot-map idea ASF borrowed in Slice 1 included a per-agent
satellite view; until now parallel agent work was only visible as a
xN badge on the station.

## How

- `apps/dashboard/src/lib/mapBoard.ts` - `RunningAgent`,
  `runningAgents`.
- `apps/dashboard/src/components/livemap/MapCanvas.tsx` - orbit
  components; `StationLayer` computes the running list once and
  passes it to the Agents node only.

## Verification

- `npm run build` - passed.
- `npm test` - 88 passed, 0 failed (87 on the base + 1 new).
- `npm run lint` - clean; `npm run format:check` - clean.
- Rule G: every touched dashboard file measures zero unsuppressed
  ESLint problems (zero before, zero after).
- Backend untouched by this PR.
- Manual: not performed. During a run with parallel item executions,
  count the dots around the Agents station and compare with the
  agent list's running rows.

## Risk & Rollback

- Security impact: none. Agent names and colours were already shown.
- Two-way door: revert the merge.
- Blast radius: the Agents station rendering only.

## Context

- Resolves: None (direct request from the project owner, 2026-11-23;
  Phase 2 of the live map).
- Relates to: PR #90 (Slice 1), PR #91 (Slice 2). Stacked on
  `feat/map-model-change` - create the PR with that branch as base,
  or merge the earlier PRs first and retarget to master.
- ADR/RFC: None.
