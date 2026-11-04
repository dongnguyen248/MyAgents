# Phase 9–11 Implementation Report

> **Date:** 2026-11-04
> **Scope (per Dong's roadmap):** Phase 9 = Dashboard connected to a real backend,
> Phase 10 = Evaluation + Metrics, Phase 11 = Harness² / optimization.
> Phase 8 (GitLab + CI) intentionally deferred. All work preserves the core
> design rules: agents only act through the core contracts and the orchestrator;
> no project-specific references in `src/`; no hard-coded providers/secrets.

---

## 1. Baseline verification (before any change)

- Unzipped the uploaded `ai-software-factory.zip` and ran the full suite:
  **1,098 tests passed, 404 subtests** — Phases 1–7 and the Teams approval part
  of Phase 8 are genuinely complete, as the summary claimed.
- Confirmed empty in the zip: `src/asf/api/` (docstring only), `src/asf/evaluation/`
  (docstring + README), `src/asf/cli/` (docstring only), `harness/` (README only).

## 2. Phase 10 — Evaluation + Metrics (`src/asf/evaluation/`)

- `MetricsService` (injected clock, thread-safe) implements **both** orchestrator
  ports from `src/asf/orchestrator/ports.py`: `MetricsRecorder.record(agent_id, result)`
  and `EventPublisher.publish(event)` — one instance plugs into the orchestrator as-is.
- Aggregates per agent / project / day: totals by status, success rate, average
  duration, average revisions, human approval rate, test pass rate (parsed from
  `TEST_REPORT` artifact verdicts), CI pass rate (explicit `record_quality` port,
  ready for Phase 8 CI), code-review rejection rate, rework rate.
- `healthScore` reproduces the dashboard formula in `apps/dashboard/src/utils/health.ts`
  exactly (30/20/20/15/15 weights, same IEEE-754 rounding behaviour).
- Outputs are dashboard-shaped camelCase dicts: `agent_metrics()`,
  `all_agent_metrics()`, `overview()` (full `MetricsOverview`), `project_outcomes()`.
- `snapshot()` / `restore()` — versioned JSON round-trip so metrics survive
  restarts alongside the SQLite execution store.
- Tests: 15 unit + 1 orchestrator integration test (metrics/events appear only
  after `flush_observations()`, second flush does not duplicate).

## 3. Phase 9 — Real backend for the dashboard (`src/asf/api/`)

- `FactoryService` (framework-free): maps orchestrator executions, approval
  requests, project profiles and metrics into the exact dashboard shapes from
  `apps/dashboard/src/types/*.ts`. Run discovery covers service-started runs,
  `track()`-ed runs, and all executions in the SQLite store per project.
- `create_app(service)` (FastAPI, imported only inside `app.py`, same pattern as
  the Teams integration) implements **every** path the dashboard's `httpApi.ts`
  already calls: `/agents`, `/agents/{id}`, `/agents/{id}/config`,
  `/agents/{id}/runs`, `/tasks` (+ filters), `/tasks/{id}`, `/workflows`,
  `/workflows/{id}`, `/projects`, `/approvals`,
  `POST /approvals/{id}/decision` (ApprovalError → 409), `/activity`,
  `/metrics/overview`, plus `/health`, `POST /runs`, `POST /runs/{id}/tick`,
  `POST /runs/{id}/cancel`, and SSE `GET /events`.
- Dashboard change (one file): `httpApi.ts` `subscribeActivity` now uses
  `EventSource(${baseUrl}/events)`; added `apps/dashboard/.env.example` with
  `VITE_API_BASE_URL=http://127.0.0.1:8000`.
- `python -m asf.api.demo` assembles the whole factory for a trial run:
  SQLite store, the real `workflows/software-development.yaml`, projects from
  `projects/`, **all seven real agents** behind one deterministic routing
  `ScriptedModelGateway`, approval policy reviewer `dashboard`, and the real
  `MetricsService`. `--selftest` drives one run headlessly to `COMPLETED`.

## 4. Phase 11 — Harness (`harness/`)

- `harness/evaluation/`: benchmark cases (calculator, todo-api, invoice-service)
  executed through the **real** Spec/Plan agents + orchestrator with scripted
  model replies; scoring = completion 0.5 + expected artifacts 0.3 + revisions
  budget 0.2. CLI: `python -m harness.evaluation.cli [--out report.json]`.
- `harness/optimization/`: a real code-loop experiment (first review always
  requests changes): `max_fixes=0` → `CODE_FIX_ESCALATED`, score 0.0;
  `max_fixes=3` → `COMPLETED` after exactly 1 fix cycle, score 1.0.
  Winner: `max_fixes=3`.
- `harness/harness2/`: `Harness2Adapter` protocol kept optional — `default_adapter()`
  returns the Null adapter (no network, Harness² not integrated); a local
  rule-based adapter turns a metrics overview into improvement suggestions
  (low health score, high revisions, low approval/test rates).

## 5. Integration fixes found by end-to-end verification (not by unit tests)

1. **Demo silently used fallback metrics.** `_load_metrics()` constructed
   `MetricsService()` with no arguments, but its constructor requires an
   injected `clock`, so the demo fell back to a stub whose `overview()` was
   always empty. Fixed to try `cls(clock=...)` first — the demo now runs on
   the real MetricsService.
2. **HTTP-started runs failed at IMPLEMENTING.** A bare `POST /runs` (only a
   requirement) lacked the step inputs/context the scripted scenario needs
   (`taskItemId`/`ref`, `project.testCommands`). `DemoFactoryService` now merges
   those demo defaults under caller-supplied values (caller wins). The generic
   `FactoryService` is unchanged.
3. **Approval metrics were keyed by agent type, run metrics by agent id**
   (`spec` vs `agent-spec`), splitting one agent into two overview rows.
   `decide_approval` now records under the artifact's `created_by` agent id.
   (One pre-existing API test asserted the old key; updated to `agent-spec`.)

## 6. Verification results (all re-run after the fixes)

| Check | Result |
|---|---|
| `pytest tests/ -q` | **1,131 passed, 404 subtests** (1,098 baseline + 33 new) |
| `ruff check src/ harness/ tests/ conftest.py` | clean |
| `mypy src/` | clean (105 files) |
| `bandit -r src/` | exit 0 (7 low findings in new code suppressed with `# nosec` + the codebase's existing convention) |
| `python -m asf.api.demo --selftest` | `SELFTEST OK`, stages SPEC_DRAFT → … → READY_TO_MERGE → COMPLETED, SPEC/PLAN/TASK/CODE present |
| Live HTTP end-to-end (real uvicorn) | `POST /runs` → approve SPEC/PLAN/TASK via `POST /approvals/{id}/decision` → **COMPLETED**, workflow 11/11 steps done, `/metrics/overview` approvalRate 1.0, testPassRate 1.0 |
| `python -m harness.evaluation.cli` | 3/3 PASS, mean score 1.00, exit 0 |
| Dashboard `npm run build` (tsc + vite) | clean |

## 7. How to run the trial

```powershell
# Backend (from repo root, venv active, deps: pip install -e .[dev,teams])
python -m asf.api.demo --port 8000            # or --selftest for headless proof

# Dashboard (another terminal)
cd apps/dashboard
copy .env.example .env                        # VITE_API_BASE_URL=http://127.0.0.1:8000
npm install
npm run dev                                   # http://localhost:5173
```

Then in the dashboard: start/observe runs via the API (`POST /runs`), approve
SPEC/PLAN/TASK from the Approvals page, and watch tasks, activity and metrics
update from real orchestrator state.

## 8. Known limitations (unchanged or deliberate)

- Phase 8 remains deferred: no real GitLab/CI adapters, so project `ci` is
  `UNKNOWN`, `ciFailures24h` is 0, and TESTING verdicts come from the
  deterministic TestAgent, not a real pipeline.
- The demo's model gateway is scripted (deterministic canned replies per
  agent). Swapping in the real Gemini gateway is a runtime-assembly change
  only — agents, contracts and orchestrator are untouched by it.
- Dashboard `COMMENT` decisions do not change approval state (the approval
  engine has no comment-only transition); the comment is echoed in the view.
- `human.avgApprovalMinutes` is reported as 0.0 — decision records carry no
  request timestamp, and no duration is fabricated.
- Metrics overview also lists the workflow action ids (`action:run-pipeline`,
  `action:await-merge`) because the orchestrator records their results through
  the same metrics port.

## 9. Note for the manual Teams flow setup (Phase 8, later)

The payload ASF actually POSTs to the Power Automate flow is
`{runId, approvalId, artifactId, artifactVersion, tenantId, teamId, channelId, card}`
where `card` is the complete Adaptive Card built by ASF
(`src/asf/integrations/teams/cards.py`). When the manual flow is resumed, the
trigger schema and the card step should consume that payload (post `card` as-is)
rather than a hand-built title/content card.
