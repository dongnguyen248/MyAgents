# api/

**Responsibility:** REST and real-time streaming API endpoints serving the dashboard and external clients.

## Architecture

Two layers, deliberately separated:

| File | Role |
|---|---|
| `service.py` | `FactoryService` — framework-free. Maps orchestrator state onto the exact dashboard JSON shapes (`apps/dashboard/src/types/*.ts`). No FastAPI import, no system-clock reads (timestamps come from runs or the injected `clock`). |
| `app.py` | `create_app(service)` — thin FastAPI adapter exposing the service over HTTP. FastAPI is imported here only; `asf.api.__init__` re-exports just `FactoryService`, so importing the package never requires FastAPI. |
| `demo.py` | Runnable assembly: SQLite store, all seven real agents behind one deterministic routing `ScriptedModelGateway`, `ApprovalPolicy(reviewers=["dashboard"])`, metrics from `asf.evaluation` when importable (guarded, with a local fallback recorder), and `uvicorn`. |

The service programs against a local `MetricsProtocol`
(`agent_metrics(agent_id)`, `overview()`, `events()`,
`project_outcomes(project_id)`, plus an optional
`record_approval_decision(...)` used via a `getattr` guard) — it never
imports `asf.evaluation`, so the evaluation package can evolve independently.

### Run discovery

The service knows about runs from three sources, merged by run id:

1. runs started through `FactoryService.start_run(...)`,
2. `store.list_executions(project_id)` for every configured project, when a
   store is supplied (this is how runs from a previous process reappear),
3. runs registered explicitly with `FactoryService.track(run_id)`.

## Endpoints

Paths are exactly the ones `apps/dashboard/src/services/api/httpApi.ts`
calls, plus run control and health:

| Method & path | Service call | Notes |
|---|---|---|
| `GET /health` | — | `{"status": "ok"}` |
| `GET /agents` | `list_agents()` | |
| `GET /agents/{id}` | `get_agent(id)` | 404 → the frontend treats it as `undefined` |
| `GET /agents/{id}/config` | `get_agent_config(id)` | 404 when unknown |
| `GET /agents/{id}/runs` | `get_agent_runs(id)` | `[]` when unknown |
| `GET /tasks?projectId&agentId&status&workflowType&priority&sinceHours` | `list_tasks(filter)` | one task per task id (latest run wins) |
| `GET /tasks/{id}` | `get_task(id)` | 404 when unknown |
| `GET /workflows` / `GET /workflows/{id}` | `list_workflows()` / `get_workflow(id)` | id is the run id (task id also accepted) |
| `GET /projects` | `list_projects()` | |
| `POST /projects` | `create_project(profile)` | body is the project-profile shape (`projects/<id>.yaml`, camelCase); 201 with the project view; duplicate id → 409; invalid profile or non-slug id → 422. The service's optional `on_project_created` hook runs before registration; the demo assembly uses it to persist the profile as `projects/<id>.yaml` (secret-scanned, never overwrites). Without a hook, projects live in memory only. |
| `PUT /projects/{id}` | `update_project(id, profile)` | the payload is merged over the stored profile, so unmanaged fields (`repository.url`, approval reviewers) survive a dashboard edit; the id cannot change (→ 422); unknown id → 404; invalid → 422. `on_project_updated` hook; the demo rewrites `projects/<id>.yaml`. The project view also exposes the editable profile fields (`description`, `workflow`, `enabledSkills`, `technologyGroups`, `approvalChannel`) for form prefill. |
| `DELETE /projects/{id}` | `delete_project(id)` | 204 on success; unknown id → 404; 409 while the project has non-terminal runs (terminal runs stay in the task/workflow history). `on_project_deleted` hook; the demo removes `projects/<id>.yaml`. |
| `GET /approvals` | `list_approvals()` | pending approvals across all known runs; each view carries `summary` (first line) and, when the artifact is known, `artifactContent` with its full text (structured payloads rendered as JSON) so reviewers can read before deciding |
| `POST /approvals/{id}/decision` | `decide_approval(id, decision, comment)` | body `{decision, comment?}`; `ApprovalError` → 409 with `{"detail": <code>}` |
| `GET /activity?agentId&taskId&projectId&limit` | `list_activity(filter)` | newest first |
| `GET /metrics/overview` | `get_metrics_overview()` | passthrough, or a valid zeroed overview without a metrics service |
| `GET /events` | SSE over `list_activity` | polls every 1s, emits only new event ids as `data: {json}` lines, stops on disconnect |
| `POST /runs` | `start_run(taskId, projectId, inputs, context)` | 201 with the workflow view |
| `POST /runs/{id}/tick` | `tick_run(id)` | ticks + flushes observations, returns the workflow view |
| `POST /runs/{id}/cancel` | `cancel_run(id)` | returns the workflow view |

CORS allows the Vite dev origins `http://localhost:5173` and
`http://127.0.0.1:5173`, all methods.

The dashboard subscribes to live activity in `httpApi.ts` via
`new EventSource(\`${baseUrl}/events\`)`; errors are swallowed (EventSource
reconnects by itself) and the returned unsubscribe closes the source.

## Shape mappings (and where they are lossy)

- **Agents** — from `AgentRegistry.list()` metadata. Status map:
  `RUNNING → BUSY`, `IDLE → IDLE` (or `BUSY` while the agent owns the
  current stage of an active run), `WAITING/ERROR/DISABLED/OFFLINE`
  passthrough. `metrics` comes from `metrics.agent_metrics(id)` with
  snake_case keys normalized to camelCase and missing fields zeroed.
  `lastActivityAt` is the newest `updatedAt` of a run the agent produced a
  result in (epoch when it never ran and no clock was injected).
- **AgentConfig** — synthesized from `AgentMetadata.configuration`;
  absent keys default to `modelVersion: "latest"`, `systemPrompt: ""`,
  `skills:` the agent's capabilities, `tools: []`, `allowedProjectIds:` all
  configured projects, `maxConcurrentTasks: 1`, `timeoutSeconds: 1800`,
  `retryPolicy: {maxRetries: 0, backoff: "none", backoffSeconds: 0}`.
- **AgentRun** — one entry per agent result in every known run:
  `SUCCESS → Completed`, `FAILED/REJECTED → Failed`, `CANCELLED →
  Cancelled`, `WAITING → Running`; `title` is the task id (runs carry no
  separate title), `startedAt` is the run's start, `durationSec` is the
  result's `metrics.duration_seconds`.
- **Tasks** — one per execution, keyed by task id (latest run wins). The
  dashboard `TaskStatus` values *are* stage names, so `run.state.stage` is
  used verbatim when it is in the dashboard list. Otherwise the stage-machine
  kind decides: `INITIAL → NEW`, `ESCALATED → <STEP>_REVIEW`,
  terminal kinds passthrough, and any other (custom/`STEP`) stage →
  `IMPLEMENTING`. Priority: the contract's `NORMAL` has no dashboard
  equivalent and maps to `MEDIUM`. `assignedAgentId` is the agent owning
  the current stage's step. `revisions` is the sum of
  `run.state.revisions`. `durationSec` is set for terminal runs.
- **Workflows** — id is the run id. Steps are built stage-by-stage from the
  workflow definition's `generated_stages()`: each definition step maps to
  a dashboard step id (`implement → implementation`, `review →
  code_review`, `test → testing`, `merge → merge`, …; unknown steps are
  skipped), and approval steps additionally emit their
  `spec_approval`/`plan_approval`/`task_approval` step. Step states are
  `done`/`active`/`pending` from the position of the current stage in the
  generated stage sequence, with `_REJECTED` stages marking
  `rejected` and a failed run marking its first unfinished step `failed`.
  Status: run status passthrough for terminal states; a run in a generated
  `*_REVIEW` stage of an approval step is `WAITING_APPROVAL` — note the
  code-review step's plain stage is literally `CODE_REVIEW`, so review
  stages are detected via the definition, never by suffix matching.
  Workflow `type` defaults to `"feature-development"` (overridable via the
  run context's `workflowType`).
- **Projects** — from `ProjectProfile` (or plain dicts): `repositoryProvider`
  from `repository.provider`, `technologies` flattened from the technology
  groups, `agentIds` = all registered agents, `ci: "UNKNOWN"` and
  `ciFailures24h: 0` (no CI adapter is wired yet). Metrics are composed
  from the project's executions (distinct result-producing agents,
  running/completed/failed counts, success rate over finished runs,
  pending approvals) and overlaid with numeric keys from
  `metrics.project_outcomes(id)` when available.
- **Approvals** — pending approvals of all known runs via
  `engine.pending_approval(run_id)` (runs whose approval lookup raises
  `ApprovalError` are skipped). `type` is the artifact type when it is one
  of `SPEC/PLAN/TASK/CODE_REVIEW/DEPLOYMENT`, else `SPEC`. `artifact` is
  the producing artifact's name, `summary` its first text line,
  `requestedByAgentId` the artifact's `created_by`. Decisions map
  `APPROVE → APPROVED`, `REJECT → REJECTED`,
  `REQUEST_CHANGES → REQUEST_CHANGES` (engine) / `CHANGES_REQUESTED`
  (dashboard); `COMMENT` appends a comment without changing state.
  A decision that does not meet a multi-approval quorum stays `PENDING`.
  Comments on the returned view are the deciding reviewer's; historical
  decision comments are not exposed by the orchestrator and are not
  reconstructed.
- **Activity** — `ActivityEvent`s from every known run's observations
  merged with `metrics.events()`, deduplicated by event id, newest first.
  `sourceKind`: `approval` when the event type starts with `APPROVAL`,
  `integration` when the metadata or type marks a CI/Git source, `agent`
  when an agent id is present, else `orchestrator`. `sourceId` is the
  agent id, else the workflow id, else `"orchestrator"`; `sourceLabel`
  mirrors it (no separate label source exists). Level: `error` for
  FAILED/ERROR types, `warn` for REJECT/ESCALAT, `success` for
  COMPLETED/APPROVED, else `info`.

## Running

```bash
.venv/bin/python -m asf.api.demo --port 8000 [--db path]
.venv/bin/python -m asf.api.demo --selftest   # headless: approves as "dashboard"
cp apps/dashboard/.env.example apps/dashboard/.env   # VITE_API_BASE_URL
```

The selftest starts a run for the first configured project, ticks and
approves through SPEC → PLAN → TASK → IMPLEMENTING → CODE_REVIEW → TESTING
→ CI → READY_TO_MERGE → COMPLETED, and asserts the SPEC/PLAN/TASK/CODE
artifacts exist. In the demo, per-step inputs pin `taskItemId: T1` and
`ref: main` for the code steps, and the run context carries the project
test commands the deterministic TestAgent requires.
