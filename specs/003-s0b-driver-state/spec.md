# S0b — driver.state

Trạng thái: [ ] đề xuất, chưa duyệt.
Phụ thuộc: S0 (002). Chặn: PR 2a.

## Problem

The workflow view cannot distinguish a run queued behind the drive
pool from one actively driving: drive membership
(`_drive_queue`/`_drive_active`) is not exposed.

## Requirements

- Add `driver.state`: `"queued" | "driving" | "idle"` to the
  workflow view's driver block, derived from queue/active
  membership (queued = in queue; driving = active and not queued;
  idle = neither).
- Keep `queries.py` line-neutral under the ratchet by extracting
  the derivation into a helper.
- Dashboard type `WorkflowDriver.state` mirrors the three values.
- No behaviour change to driving, adoption, or scheduling.
