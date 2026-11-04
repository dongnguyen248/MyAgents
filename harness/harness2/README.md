# harness/harness2/
Adapter seam for evaluating/integrating Google Harness² (recursive improvement).

Google Harness² is **not implemented / not integrated**: this package makes
no network calls and Harness² stays optional and off by default.

- `adapter.py` — the `Harness2Adapter` protocol (`assess(metrics_overview)
  -> list[Suggestion]`) and the `Suggestion` model (`target_agent_id`,
  `kind`, `message`, `metric`, `value`).
- `NullHarness2Adapter` — the default (`default_adapter()`): `available`
  is `False` and `assess()` always returns `[]`.
- `LocalHarness2Adapter` — a deterministic, offline stand-in applying
  simple rules to a MetricsOverview-shaped dict (see
  `apps/dashboard/src/types/metrics.ts`): `healthScore < 70` ->
  investigate the agent, `avgRevisions > 1.5` -> tighten prompt/spec
  template, `humanApprovalRate` / `human.approvalRate < 0.5` -> review the
  artifact template, `quality.testPassRate < 0.8` -> strengthen test
  generation.

Runtime metrics from `src/asf/evaluation/` feed this seam; a real Harness²
adapter can be dropped in behind the same protocol later.
