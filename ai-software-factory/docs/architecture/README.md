# Architecture Overview

## 1. Core architecture
The **orchestrator** is the single coordinator. For a work item it asks the **workflow** definition what comes next, moves the item through the **state machine**, dispatches the right **agent**, receives an **artifact**, and requests **approval** when the workflow demands it. Rejections carry feedback back to the producing agent.

```text
Orchestrator -> Agent -> Artifact -> Approval -> Orchestrator -> next Agent
```
Shared interfaces live in `core/contracts/`. `core/configuration/` merges global -> project -> workflow -> agent settings. `core/evaluation/` records runtime metrics.

## 2. Agent architecture
Seven agents (spec, plan, task, implement, review, test, fix), each with `prompts/`, `instructions/`, `tools/`, `skills/`, `tests/`. Agents are stateless w.r.t. the workflow, never call each other, never own approval, and contain nothing project- or vendor-specific.

## 3. Skill architecture
Skills are knowledge packages (java, spring, react, python, git, testing, security, ...). Projects enable/disable them; the orchestrator resolves enabled skills per agent run.

## 4. Integration architecture
Ports & adapters: core/agents depend on interfaces; `integrations/` holds adapters (GitLab, Teams, notifications, CI, LLM). Swapping Teams for Slack, GitLab for GitHub, or one LLM vendor for another touches only an adapter and a project/global config value.

## 5. Project configuration
`projects/<id>.yaml` selects repository provider, technology, workflow, approval channel and enabled skills. Configuration only; no secrets, no code.

## 6. Future Harness² integration
`harness/` is isolated from runtime. `evaluation/` scores agents, `optimization/` tests prompt/skill/tool/config changes, `harness2/` is reserved for the Harness² adapter. Runtime metrics from `core/evaluation/` feed it.

## Decisions & deviations from the proposed tree
- Added `core/contracts/` - without a home for interfaces, Rules 2-5 have nowhere to live.
- Added `integrations/llm/` - Rule 5 (model independence) needs an adapter slot like the other external services.
- Everything else follows the requested structure.

## Next step
Design **Orchestrator + State Machine + Agent contracts**.

## Dashboard Architecture

`apps/dashboard` is the **Control Tower**: a generic web UI for observing and managing the whole factory (agents, tasks, workflows, approvals, projects, metrics, live activity). It is a single React + TypeScript + Vite app, independent from the platform code.

```text
Dashboard (pages, features, components)
   ↓
Frontend Services (services/<domain>)
   ↓
API Contract (FactoryApi + src/types)
   ↓
AI Software Factory Backend (REST + real-time events + metrics)
```

Today the "API Contract" layer is satisfied by an in-browser mock (`mockApi`). A REST skeleton (`httpApi`) already exists and is enabled by `VITE_API_BASE_URL`.

```text
                    WEB DASHBOARD
                         │
          ┌──────────────┼──────────────┐
       REST API      WebSocket/SSE     Metrics
          └──────────────┼──────────────┘
                  AI SOFTWARE FACTORY
                   (Orchestrator → Agents → GitLab → CI → Quality Gate)
```

### Why the dashboard is separate from `core/`
It has a different release cadence, runtime (browser) and audience. `core/` must not depend on UI concerns, and the UI must be replaceable without touching the engine.

### Why the dashboard contains no agent logic
It only displays state and (later) sends commands such as approval decisions or configuration changes. Agent behaviour stays in `agents/` and is driven by the orchestrator. This keeps Rules 1–4 intact: the UI is another client of the platform, not part of it.

### Why it uses API contracts
`src/types/*` and `FactoryApi` define what the backend must provide. Pages never know whether data comes from a mock, REST or a stream, so connecting the real backend does not require redesigning the UI. These types are also the starting point for the backend's API schema (to be aligned with `core/contracts/`).

### Mock data is temporary
`src/mocks/` exists only so the UI can be designed and reviewed with realistic data. Components must never import it; only `mockApi` does. It is deleted once the backend exists.

### Real-time events (WebSocket / SSE)
Live activity uses `FactoryApi.subscribeActivity`. The mock emits timer events; the real implementation will use Server-Sent Events (simple, one-way, auto-reconnect) or WebSocket (if bi-directional control is needed). Only `httpApi.ts` changes.

### Health score
Besides task counts, each agent gets a Health Score (success, human approval, CI pass, test pass, revision count) so the dashboard shows which agents are *good*, not just busy. It feeds the future `harness/` evaluation work.
