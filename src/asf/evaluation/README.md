# src/asf/evaluation/

**Responsibility:** collect runtime metrics per agent/workflow run and aggregate
them into the dashboard's `AgentMetrics` / `MetricsOverview` shapes.
(Offline experiments live in `harness/`.)

## MetricsService

`MetricsService(clock=...)` (in `service.py`) is the concrete implementation of
both orchestrator write-side ports defined in `src/asf/orchestrator/ports.py`:

- `record(agent_id, result)` — `MetricsRecorder`. One orchestrator result
  becomes one `AgentRunRecord` (status, `RunMetrics.duration_seconds`,
  `RunMetrics.revision_count`, attempt). The project/task attribution is
  derived from the result's events, because `AgentResult` itself carries no
  project id; results without events are recorded but unattributed.
- `publish(event)` — `EventPublisher`. Events are stored as copies;
  `events()` returns fresh copies in chronological order.

Pass the same instance as both `metrics=` and `events=` to `Orchestrator`;
the orchestrator only delivers them when `flush_observations()` is called
(at-least-once delivery — consumers deduplicate by event id / request id).

Artifacts on a result are parsed defensively for quality samples, and unknown
shapes are ignored (recording never raises because of an artifact):

- `TEST_REPORT` — the verdict is read from the nested
  `content["report"]["verdict"]` the TestAgent emits (`PASS`/`FAIL`)
  and becomes a `TEST` sample for the recording agent.
- `CODE_REVIEW` — the verdict is read from the nested
  `content["review"]["verdict"]` the ReviewAgent emits
  (`APPROVE`/`CHANGES_REQUESTED`) and becomes a `REVIEW` sample.

Two explicit inputs cover what results cannot express:

- `record_approval_decision(project_id=..., task_id=..., agent_id=...,
  decision=..., at=None)` with `decision` in
  `APPROVED | REJECTED | REQUEST_CHANGES`. The human approval rate is
  `APPROVED / all decisions`. `at` defaults to the injected clock.
- `record_quality(project_id=..., task_id=..., agent_id=..., kind=...,
  passed=...)` with `kind` in `TEST | CI | REVIEW`. This is the only source
  of CI samples until a CI agent exists (Phase 8), and an alternative source
  for explicit test/review samples.

Internal records are the pydantic models in `models.py`
(`AgentRunRecord`, `ApprovalRecord`, `QualityRecord`).

## Outputs (dashboard shapes, camelCase)

- `agent_metrics(agent_id)` / `all_agent_metrics()` — `AgentMetrics`:
  `total, completed, running, failed, cancelled, successRate,
  avgDurationSec, avgRevisions, humanApprovalRate, testPassRate, ciPassRate,
  healthScore`.
- `overview()` — `MetricsOverview`: per-date `daily` buckets, a `human`
  section (approval/rejection rates, average revisions, per-date rates), a
  `quality` section (code-review rejection rate, test/CI pass rates, rework
  rate, per-date rates) and `agents` comparison rows.
- `project_outcomes(project_id)` — `{running, completed, failed, successRate}`
  for the API layer to compose `ProjectMetrics`.

`healthScore` mirrors `apps/dashboard/src/utils/health.ts` exactly:
`round(100 * (0.30*successRate + 0.20*humanApprovalRate + 0.20*ciPassRate +
0.15*testPassRate + 0.15*max(0, 1 - (avgRevisions - 1) / 3)))`, with halves
rounded up as `Math.round` does.

## Human vs AI decisions (Phase 12)

Every recorded decision carries `reviewer_kind` (`HUMAN | AI`).
`humanApprovalRate` is computed over HUMAN decisions only; AI review
decisions (recorded automatically from `AI_REVIEW_COMPLETED` events,
attributed to the reviewer agent) never enter it. When an agent has
**no human decisions at all**, `humanApprovalRate` is `null` — not
`0.0` — and the health score re-normalises without the human term:

`healthScore = round(100 * (0.30*successRate + 0.20*ciPassRate +
0.15*testPassRate + 0.15*revisionScore) / 0.80)`

The same rule applies to the overview's `human.approvalRate` /
`rejectionRate`: with no human decisions they are `null` (undefined),
so downstream consumers that treat `null` as "no data" — including the
Harness² improvement trigger — do not fire on AI-reviewed work.
`agent_metrics` also reports `humanDecisions` / `aiDecisions` counts,
and the overview's `human` section reports `decisions` / `aiDecisions`.

## AI review metrics

`overview()` includes an `aiReview` block computed from the published
review events. A *gate* is one (run, step) with at least one completed
AI review round (`AI_REVIEW_COMPLETED`):

- `aiReviewFirstPassRate` — gates whose first completed round approved,
  over all gates.
- `aiReviewAvgRounds` — mean completed rounds per gate.
- `aiReviewEscalationRate` — gates escalated with an AI reason
  (`MAX_REVISIONS`, `NO_PROGRESS`, `REVIEWER_FAILED`, `BUDGET`) over
  gates that reached an outcome (approved or escalated; an
  escalation-only gate, e.g. a budget stop at claim time, still counts).
- `aiReviewStagnationRate` — gates with at least one
  `AI_REVIEW_STAGNATION` event, over all gates.

The block also carries the raw `gates` and `escalations` counts.

## Aggregation choices

- Agent `successRate = completed / total`, where `total` is every recorded
  result for the agent.
- The dashboard has no bucket for a `REJECTED` result, so rejected runs count
  in the `failed` bucket (status mapping: `SUCCESS → completed`,
  `WAITING → running`, `FAILED | REJECTED → failed`,
  `CANCELLED → cancelled`). They are failures of outcome, not a separate
  outcome class, and they lower the success rate.
- "Finished" rates — the daily buckets and `project_outcomes` — use
  `completed / (completed + failed)`; running and cancelled work is excluded
  from those denominators.
- `reworkRate` is the share of recorded results with `revision_count > 0`.
- Any rate with a zero denominator is `0.0`.
- `human.avgApprovalMinutes` is `0.0`: approval durations are not tracked
  (a decision is recorded with its decision time only, no request time), and
  the service does not fabricate one.

## Persistence and concurrency

`snapshot()` returns a JSON-safe dict of all records (runs, approvals,
quality samples, events). `MetricsService.restore(data, clock=...)` builds a
new service from it, and `load(data)` replaces an existing service's state,
so metrics can survive restarts alongside the MariaDB execution store.

The service is thread-safe: all public methods serialise on one lock, and
all getters return fresh dicts / copies, never internal state.
