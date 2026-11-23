# feat(live-map): JSONL replay - record runs and play them back

## What

Phase 2, item 4 (option (a), chosen by the project owner). Every
live-map pulse is now also recorded to a per-run JSONL file beside
the run database, and the Live Map page gains a Replay mode.

- Recording: `MapReplayStore` (`src/asf/api/service/map_replay.py`)
  is fed by the hub as a sink. The sink only enqueues; one daemon
  writer thread owns all disk I/O, so the tap stays non-blocking.
  Files live in `<data_dir>/map-runs/<run_id>.jsonl`, owner-only
  (0600), one contract JSON per line - the same dicts the snapshot
  serves. When the hub marks a run closed, a footer line is appended
  with the hub's cumulative counters, the budget and a `truncated`
  flag.
- Caps: past 2000 events or 1 MB per run, event writes stop but the
  footer still lands with the true totals; the UI shows a
  "Replay bị cắt" (truncated) badge and takes its totals from the
  footer. A run that dies mid-flight has no footer; the UI shows
  "Chưa hoàn tất" (incomplete) and the file still opens.
- Retention, swept at startup: files older than 7 days or beyond
  the newest 50 runs are deleted. The replay list is read from the
  directory, so runs recorded before a backend restart are listed.
- Routes: `GET /map/replays` (summaries) and `GET /map/replay`
  (events + footer totals), registered only when a store exists.
  Run ids must match a tight pattern (letters, digits, `-`, `_`;
  no dots or separators) and the resolved path is verified to stay
  inside the directory - path traversal is rejected with 404.
- Disk failure: the writer disables itself and logs once; agents
  and the hub are unaffected (tested at the gateway level).
- UI: a Live/Replay mode switch on the Live Map page. Replay mode
  offers a run picker, play/pause, 1x/2x/4x speeds and a scrub bar
  over the run's real timeline. The board is built by `replayBoard`,
  which runs the same `applyMapEvent` reducer as live over the
  pulses inside the cursor - a test proves a full replay rebuilds
  exactly the live board at the end of the run.
- Tests: 11 backend tests (write + footer, event cap, byte cap,
  incomplete run, listing after a fresh store, retention sweep,
  0600 permissions, traversal rejection at store and route level,
  routes absent without a store, disk failure leaving an agent
  result unchanged) and 2 dashboard tests (full-replay board equals
  the live board; cursor prefix).

## Why

Pulses were memory-only: once the backend restarted or the hub
swept a finished run, there was no way to re-watch what the agents
did. The owner chose JSONL beside the database over a MariaDB table
(no storage-contract change) and over step-level reconstruction
from observations (which loses the model and tool pulses that make
the map worth replaying).

## How

- `src/asf/api/service/map_replay.py` - the store: sink, writer
  thread, caps, footer, retention, listing and reading.
- `src/asf/api/service/map_hub.py` - optional event sink and close
  sink hooks, both called inside emit's existing failure guard;
  `mark_closed` notifies the close sink once.
- `src/asf/api/service/map_publisher.py` - `install_live_map`
  creates and starts the store when given a data dir.
- `src/asf/api/demo.py` - `_RegistryDeps` carries `data_dir` to the
  install call (one added field, lines rewritten in place).
- `src/asf/api/map_routes.py` - the two replay routes, gated on an
  active store.
- `.gitignore` - `/data/map-runs/`.
- `apps/dashboard/src/types/map.ts` - `MapReplaySummary`,
  `MapReplay`.
- `apps/dashboard/src/services/api/contract.ts`,
  `src/services/api/httpApi.ts`, `src/services/api/mockApi.ts` -
  `getMapReplays` / `getMapReplay` (mock returns none).
- `apps/dashboard/src/lib/mapBoard.ts` - `replayDurationMs`,
  `replayBoard` on top of the live reducer.
- `apps/dashboard/src/pages/LiveMap/ReplaySection.tsx`,
  `src/pages/LiveMap/useReplay.ts` - picker, transport, playback
  engine (keyed player state, pulses for crossed events).
- `apps/dashboard/src/pages/LiveMap/LiveMapPage.tsx` - the
  Live/Replay mode switch.
- `apps/dashboard/src/styles/global.css` - replay bar and badge
  styles (append-only).

## Verification

- `pytest -q` - 2164 passed, 8 skipped, 425 subtests passed
  (2153 on the base + 11 new).
- `ruff check src tests` - all checks passed;
  `ruff format --check src tests harness` - 440 files formatted.
- `mypy src` - success, no issues in 184 source files.
- `bandit -c .bandit -r src -q` - clean.
- `python scripts/check_code_structure.py --baseline .code-structure-baseline.json` - 0 violations, 224 measured (baseline unchanged).
- `gitleaks git --redact .` - no leaks found.
- `python -m asf.api.demo --selftest` - SELFTEST OK, COMPLETED.
- Live smoke (sandbox): a scripted self-test run recorded 58
  pulses; the stored replay reads back complete with footer
  counters equal to the hub's. With `ASF_LIVE_MAP=0`: no hub, no
  store, no replay routes, no `map-runs` directory created, and the
  self-test still passes.
- Dashboard: `npm run build` passed; `npm test` 90 passed (88 + 2
  new); `npm run lint` clean; `npm run format:check` clean;
  Rule G - every new or touched file measures zero unsuppressed
  ESLint problems, and `httpApi.ts` / `mockApi.ts` match their
  recorded suppression counts exactly (no new rule, no growth).
- Manual: not performed. A reviewer should, on the real backend:
  run any run to completion, restart the backend, open Live map ->
  Replay, and confirm the run is listed, plays back with pulses,
  scrubs, and shows footer totals; kill the backend mid-run and
  confirm that run's replay opens with the incomplete badge.

## Risk & Rollback

- Security impact: replay files persist the map's metadata-only
  pulses (names, hosts, two-level paths - the same sanitized labels
  as live, never content) to disk beside the database, owner-only
  (0600) under a 0700 directory, bounded by per-run caps and the
  7-day / 50-run retention. The replay routes share the API's
  existing no-auth local posture the README already warns about;
  run-id validation plus a resolved-path check block traversal.
  No new dependencies, secrets or config keys.
- Two-way door: revert the merge, or run with `ASF_LIVE_MAP=0`
  (no writer, no routes, no directory). Leftover `map-runs` files
  are inert and can be deleted by hand.
- Blast radius: the hub gains two optional hooks that default to
  absent; with no store installed, emit behaves exactly as before.
  A writer failure degrades to "no replay for new runs" only.

## Context

- Resolves: None (direct request from the project owner, 2026-11-23;
  Phase 2 item 4 of the live map, option (a) chosen by the owner).
- Relates to: PR #90 (Slice 1), PR #91 (Slice 2) and the Phase 2
  items 0-3 branches. Stacked on `feat/map-pr-link` - create the PR
  with that branch as base, or merge the earlier PRs first and
  retarget to master.
- ADR/RFC: None.
