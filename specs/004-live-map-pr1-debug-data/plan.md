# PR 1 — Plan (as implemented)

- Ambient wall clock installed by `install_live_map`; the models
  layer never reads the wall clock itself (purity rules).
- Duck-typed `endpoint_label` on the settings gateway; no contract
  change.
- Gates at delivery: 2246 backend tests passed (master 2224 + 22),
  dashboard 93, ratchet 0/222, selftest OK.
- Delivery: Dong pushes `feat/map-debug-data`, creates and merges
  the PR; draft `PR-DRAFT-PR1.md` in the mapdebug worktree.
