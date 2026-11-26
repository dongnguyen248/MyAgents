# Live Map PR 1 — Debug data

Trạng thái: [~] đã code, chưa push (branch `feat/map-debug-data`).
Phụ thuộc: chuỗi S0 → S0b → PR 1 → PR 2a (PR 1 là điều kiện của PR 2a).
Chặn: PR 1b, PR 2a, PR 2b.

## Scope

Make the Live Map usable for debugging agents, metadata only:
events never carry prompt/response content, keys, or full base
URLs (host:port labels only); the map must never break a run.

- `MapEvent` gains `attempt` and `prompt_chars`.
- `endpoint_label(url)` = host:port; per-agent endpoint label from
  model settings (scripted → none).
- MapTapGateway timestamps use a monotonic floor so model pulses
  never end before they start.
- Snapshot gains `tracked` (hub membership).
- Hub limits configurable via env, invalid values fall back to
  defaults (16 runs, 600 s closed TTL).
- Dashboard: types only.
