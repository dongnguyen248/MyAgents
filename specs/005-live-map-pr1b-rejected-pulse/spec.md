# Live Map PR 1b — Rejected pulse

Trạng thái: [~] đã code, chưa push (branch `feat/map-rejected-pulse`, stacked trên PR 1).
Phụ thuộc: PR 1 (004). Chặn: PR 2c.

## Scope

Exactly one metadata-only `agent`/`moment`/`error` pulse per
Spec/Plan/Task output rejection, code `LLM_INVALID_RESPONSE`,
counts-only label. No pulse for empty responses, oversized replies,
or Plan milestone/Linked-SPEC rejections.
