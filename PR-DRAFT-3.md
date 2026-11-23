# feat(live-map): show the run's PR/MR link in the detail panel

## What

Phase 2, item 3. The map snapshot now carries the run's
change-request link, taken from the hosting metadata already stored
in the run record, and the dashboard's Detail panel shows it as
`PR / MR  #<number>` linking to the URL.

- Backend: `_hosting_link` in `src/asf/api/map_routes.py` scans the
  run's stored step results for a `changeRequest` output (written by
  the run-pipeline / await-merge hosting actions) and exposes only
  `{url, number}` on `/map/snapshot` as `hosting`. The URL must be
  http(s) and the number non-empty; anything else - no hosting, a
  skipped pipeline, a malformed ref - yields `null`, and the panel
  simply hides the row. No error is ever raised for a missing link.
  The URL is additionally rebuilt from scheme + host + port + path
  only (follow-up commit): userinfo, query and fragment are stripped,
  so a provider URL carrying credentials or tokens can never leak
  them into the snapshot - covered by a test whose URL carries a
  marker token in all three places.
  The public workflow view omits step outputs by design, so the
  extractor reads the run record's results directly (same package,
  read-only); the rest of the hosting output (branch, pipeline
  payload) is never exposed.
- Dashboard: `MapSnapshot.hosting` / `MapHosting` types, plumbed
  through `useLiveMapData` into the Detail card. The link row sits
  at the top of the detail panel - visible for the run as a whole
  (nothing selected) and above any selected pulse's details.
  Only the URL and the number render; no hosting content.
- Tests: 3 new route tests (link exposed from the last matching
  result; hidden when metadata is absent, the URL is not http(s),
  or the number is missing; userinfo/query/fragment stripped with
  none of the marker tokens anywhere in the payload).

## Why

Once CI opens a PR/MR, the operator had to leave the map and hunt
for the link; the run already knew it.

## How

- `src/asf/api/map_routes.py` - `_hosting_link`,
  `_change_request_link`, snapshot payload gains `hosting`.
- `apps/dashboard/src/types/map.ts` - `MapHosting`, snapshot field.
- `apps/dashboard/src/pages/LiveMap/useLiveMapData.ts` - hosting in
  the view state, refreshed with each snapshot (every 5 s, so the
  link appears shortly after the CI step lands it).
- `apps/dashboard/src/pages/LiveMap/LiveMapPage.tsx`,
  `src/components/livemap/MapSidePanel.tsx` - plumbing and the
  `HostingLink` row.

## Verification

- `pytest -q` - 2153 passed, 8 skipped, 425 subtests passed
  (2150 on the base + 3 new).
- `ruff check src tests` - all checks passed;
  `ruff format --check src tests harness` - 438 files formatted.
- `mypy src` - success, no issues in 183 source files.
- `python scripts/check_code_structure.py --baseline .code-structure-baseline.json` - 0 violations, 224 measured (baseline unchanged).
- `python -m asf.api.demo --selftest` - SELFTEST OK, COMPLETED.
- Dashboard: `npm run build` passed; `npm test` 88 passed;
  `npm run lint` clean; `npm run format:check` clean; Rule G -
  every touched file measures zero unsuppressed ESLint problems.
- Manual: not performed. Needs a run against a project with hosting
  configured (the write paths are still only fake-transport tested):
  after the CI step opens the PR/MR, the Detail panel should show
  the link within one snapshot refresh.

## Risk & Rollback

- Security impact: the snapshot additionally exposes the PR/MR URL
  and number of the operator's own project - the same metadata-only
  posture as the rest of the map, on the same unauthenticated local
  API the README already warns about. Branch names, pipeline
  payloads and tokens are not exposed.
- Two-way door: revert the merge, or run with `ASF_LIVE_MAP=0`.
  The snapshot field is additive; older dashboards ignore it.
- Blast radius: the map snapshot builder only; a failure inside the
  extractor degrades to `hosting: null`, never to a failed snapshot.

## Context

- Resolves: None (direct request from the project owner, 2026-11-23;
  Phase 2 of the live map).
- Relates to: PR #90 (Slice 1), PR #91 (Slice 2). Stacked on
  `feat/map-agent-orbits` - create the PR with that branch as base,
  or merge the earlier PRs first and retarget to master.
- ADR/RFC: None.
