# S0b — Plan

- `_driver_view` (queries.py) gains the state field via a helper
  next to the S0 fallback module; one line in, one line offset.
- TS type update in `types/workflow.ts`; no UI change in this PR
  (PR 2a consumes it for the "queued behind the run pool"
  empty-state cause).
- Tests: queued run → "queued"; popped run → "driving"; unknown
  run → "idle". Separate small PR after S0 merges.
