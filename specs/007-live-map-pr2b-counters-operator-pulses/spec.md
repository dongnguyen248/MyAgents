# Live Map PR 2b — Error counting and operator pulses

Trạng thái: [ ] chưa duyệt.
Phụ thuộc: PR 1 (004). Chặn: PR 2c.

## Requirements

- `counters.errors` also counts `moment` pulses with status error
  (documented semantic change; this makes PR 1b rejected pulses
  visible in counters).
- Operator pulses at six service sites: cancel_run, retry_run,
  resume_run, resume_escalation, skip_tests_run,
  approve_escalated_run. Action-name labels only, through the
  fail-safe emit path; metadata only, never content.
