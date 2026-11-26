# Live Map PR 2a — Truthful auto-selection

Trạng thái: [ ] chưa duyệt.
Phụ thuộc: S0 (002), S0b (003), PR 1 (004) đã merge.

## Requirements

- Auto-selection must not trust `w.status === 'RUNNING'`: sort by
  startedAt desc, check at most 3 candidates' snapshots, prefer
  tracked with events, then non-terminal by stage; otherwise show
  an explicit status-unverified state (at most 3 extra snapshot
  requests at page load).
- UNKNOWN renders as "Status unknown", never RUNNING, in the Live
  Map header and dropdown label.
- Empty-state causes include "queued behind the run pool" (needs
  S0b's `driver.state`).
- Centre-cell units, foldKey with attempt and no folding of error
  rows, Store/Skills removal with an unknown-station no-crash test.
