# Architecture Overview

## 1. Core architecture
The **orchestrator** is the single coordinator. For a work item it asks the **workflow** definition what comes next, moves the item through the **state machine**, dispatches the right **agent**, receives an **artifact**, and requests **approval** when the workflow demands it. Rejections and change requests carry feedback back to the producing agent.

```text
Orchestrator -> Agent -> Artifact -> Approval -> Orchestrator -> next Agent
```
Shared data schemas and ports live in `contracts/`. They use JSON Schema Draft 2020-12 for serializable, language-neutral data and describe service ports without implementing storage, transport, or provider behavior. `src/asf/configuration/` merges global -> project -> workflow -> agent settings. `src/asf/evaluation/` records runtime metrics.

## 2. Contract and communication model
An agent receives a standardized `AgentRequest`, validates it, and returns an `AgentResult`. Artifacts can contain inline content or an opaque external-storage reference. The orchestrator passes workflow-relevant artifacts between steps and remains responsible for sequencing and approval gates.

Agents do not directly call each other. A direct chain would couple agent implementations and make it difficult to change, retry, audit, or approve individual steps. With the orchestrator mediating through artifacts and contracts, each agent can remain independently replaceable.

`ActivityEvent` is the platform's transport-neutral activity record. Events correlate to project/task/workflow/agent identifiers and can later be published to dashboards, logging, evaluation, or audit through an `EventPublisher` adapter. The contract does not implement WebSocket/SSE or a dashboard backend.

Approval is a platform service: an `ApprovalRequest` identifies the artifact and workflow context, and an `ApprovalDecision` records the reviewer, decision, and comment. A rejection or `REQUEST_CHANGES` decision returns feedback to the orchestrator; the orchestrator may include it in a subsequent agent request. Agents do not own approval or notification integrations.

## 3. Agent architecture
Seven agents (spec, plan, task, implement, review, test, fix) in `src/asf/agents/`, each with `prompts/`, `instructions/`, `tools/`, `skills/`, `tests/`. Agents are stateless w.r.t. the workflow, never call each other, never own approval, and contain nothing project- or vendor-specific.

## 4. Skill architecture
Skills are knowledge packages (java, spring, react, python, git, testing, security, ...). Projects enable/disable them; the orchestrator resolves enabled skills per agent run.

## 5. Integration architecture
Ports & adapters: core/agents depend on interfaces in `contracts/`; `src/asf/integrations/` holds external service adapters (GitLab, Teams, notifications, CI) and `src/asf/models/providers/` holds LLM provider adapters. Swapping Teams for Slack, GitLab for GitHub, or one LLM vendor for another touches only an adapter and a project/global config value.

## 6. Project configuration
`projects/<id>.yaml` selects repository provider, technology, workflow, approval channel and enabled skills. Configuration only; no secrets, no code.

The normalized `Project` contract has no project-specific fields and represents repository and technology as data, so the same platform contracts apply to all projects.

## 7. Provider independence
Agent requests and results do not expose a specific LLM provider. Model selection and provider-specific request/response translation belong behind future integration ports and adapters. Likewise, repository, CI, and approval providers are not embedded in core contracts; new providers implement the relevant port without requiring project-specific agents or workflows.

## 8. Platform design rules
1. `src/asf/`, `contracts/`, `skills/` never reference a specific project.
2. Agents never call each other; the orchestrator mediates via artifacts + approvals.
3. Human approval is a platform capability, not part of any agent.
4. External services live in `src/asf/integrations/` and `src/asf/models/providers/` behind interfaces.
5. No LLM provider is hard-coded.
6. Agents never perform side effects (shell, git, network including LLM calls, filesystem, database) directly. They act only through ports defined in contracts/ports.md; implementations live in src/asf/tools, src/asf/execution, src/asf/models, src/asf/storage and src/asf/integrations, and are wired in by the orchestrator.

## 9. Future Harness² integration
`harness/` is isolated from runtime. `evaluation/` scores agents, `optimization/` tests prompt/skill/tool/config changes, `harness2/` is reserved for the Harness² adapter. Runtime metrics from `src/asf/evaluation/` feed it.

## 10. Repository layout

```text
ai-software-factory/
├── src/asf/                    # Core Python package ("asf")
│   ├── orchestrator/           # Agent sequencing and workflow progression
│   ├── workflow/               # Declarative workflow definitions
│   ├── state_machine/          # Item states and legal transitions
│   ├── approval/               # Human review service
│   ├── evaluation/             # Metrics recording
│   ├── configuration/          # Configuration models & loaders
│   ├── agents/                 # Specialized agent implementations
│   ├── integrations/           # External service adapters (GitLab, Teams, CI)
│   ├── models/                 # Model gateway & LLM provider adapters
│   ├── contracts/              # Python schema bindings
│   ├── tools/                  # Agent tool execution adapters
│   ├── execution/              # Process runners & isolation sandboxes
│   ├── storage/                # Repository persistence adapters
│   ├── api/                    # REST / streaming endpoints
│   └── cli/                    # CLI commands
├── contracts/                  # Language-neutral JSON Schemas and ports
│   ├── schemas/                # contracts.schema.json (Draft 2020-12)
│   ├── ports.md                # Language-neutral ports specification
│   └── README.md
├── apps/dashboard/             # Control Tower frontend (React + TypeScript + Vite)
├── skills/                     # Reusable knowledge packages
├── templates/                  # Artifact templates (SPEC, PLAN, TASK, etc.)
├── projects/                   # Project profiles (YAML)
├── config/                     # Configuration definitions
├── harness/                    # Harness² research and offline evaluation
├── tests/                      # Unit and integration tests
├── docs/                       # Architecture documentation
├── scripts/                    # Developer and operations scripts
└── docker/                     # Container images and deployment configs
```

**Rationale:** The `src/` layout with a single top-level importable package named `asf` avoids generic top-level namespace collisions (such as `core` or `agents`) with other installed packages or standard library extensions.

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

### Why the dashboard is separate from `src/asf/`
It has a different release cadence, runtime (browser) and audience. `src/asf/` must not depend on UI concerns, and the UI must be replaceable without touching the engine.

### Why the dashboard contains no agent logic
It only displays state and (later) sends commands such as approval decisions or configuration changes. Agent behaviour stays in `src/asf/agents/` and is driven by the orchestrator. This keeps Rules 1–4 intact: the UI is another client of the platform, not part of it.

### Why it uses API contracts
`src/types/*` and `FactoryApi` define what the backend must provide. Pages never know whether data comes from a mock, REST or a stream, so connecting the real backend does not require redesigning the UI. These types are also the starting point for the backend's API schema (to be aligned with `contracts/`).

### Mock data is temporary
`src/mocks/` exists only so the UI can be designed and reviewed with realistic data. Components must never import it; only `mockApi` does. It is deleted once the backend exists.

### Real-time events (WebSocket / SSE)
Live activity uses `FactoryApi.subscribeActivity`. The mock emits timer events; the real implementation will use Server-Sent Events (simple, one-way, auto-reconnect) or WebSocket (if bi-directional control is needed). Only `httpApi.ts` changes.

### Health score
Besides task counts, each agent gets a Health Score (success, human approval, CI pass, test pass, revision count) so the dashboard shows which agents are *good*, not just busy. It feeds the future `harness/` evaluation work.

## Decisions & deviations from the proposed tree
- Added `contracts/` - without a home for interfaces, Rules 2-5 have nowhere to live.
- Added `src/asf/models/providers/` - Rule 5 (model independence) needs an adapter slot like the other external services.
- Clean `src/asf` layout for Python packaging with single top-level package namespace `asf`.
- Everything else follows the requested structure.

## Next step
Implement the orchestrator and state machine against the established contracts in a later phase.
