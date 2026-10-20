# Architecture Overview

## 1. Core architecture
The **orchestrator** is the single coordinator. For a work item it asks the **workflow** definition what comes next, moves the item through the **state machine**, dispatches the right **agent**, receives an **artifact**, and requests **approval** when the workflow demands it. Rejections and change requests carry feedback back to the producing agent.

```text
Orchestrator -> Agent -> Artifact -> Approval -> Orchestrator -> next Agent
```
Shared data schemas and ports live in `core/contracts/`. They use JSON Schema Draft 2020-12 for serializable, language-neutral data and describe service ports without implementing storage, transport, or provider behavior. `core/configuration/` merges global -> project -> workflow -> agent settings. `core/evaluation/` records runtime metrics.

## 2. Contract and communication model
An agent receives a standardized `AgentRequest`, validates it, and returns an `AgentResult`. Artifacts can contain inline content or an opaque external-storage reference. The orchestrator passes workflow-relevant artifacts between steps and remains responsible for sequencing and approval gates.

Agents do not directly call each other. A direct chain would couple agent implementations and make it difficult to change, retry, audit, or approve individual steps. With the orchestrator mediating through artifacts and contracts, each agent can remain independently replaceable.

`ActivityEvent` is the platform's transport-neutral activity record. Events correlate to project/task/workflow/agent identifiers and can later be published to dashboards, logging, evaluation, or audit through an `EventPublisher` adapter. The contract does not implement WebSocket/SSE or a dashboard backend.

Approval is a platform service: an `ApprovalRequest` identifies the artifact and workflow context, and an `ApprovalDecision` records the reviewer, decision, and comment. A rejection or `REQUEST_CHANGES` decision returns feedback to the orchestrator; the orchestrator may include it in a subsequent agent request. Agents do not own approval or notification integrations.

## 3. Agent architecture
Seven agents (spec, plan, task, implement, review, test, fix), each with `prompts/`, `instructions/`, `tools/`, `skills/`, `tests/`. Agents are stateless w.r.t. the workflow, never call each other, never own approval, and contain nothing project- or vendor-specific.

## 4. Skill architecture
Skills are knowledge packages (java, spring, react, python, git, testing, security, ...). Projects enable/disable them; the orchestrator resolves enabled skills per agent run.

## 5. Integration architecture
Ports & adapters: core/agents depend on interfaces; `integrations/` holds adapters (GitLab, Teams, notifications, CI, LLM). Swapping Teams for Slack, GitLab for GitHub, or one LLM vendor for another touches only an adapter and a project/global config value.

## 6. Project configuration
`projects/<id>.yaml` selects repository provider, technology, workflow, approval channel and enabled skills. Configuration only; no secrets, no code.

The normalized `Project` contract has no project-specific fields and represents repository and technology as data, so the same platform contracts apply to VHPC, VNPC, ERP, and future projects.

## 7. Provider independence
Agent requests and results do not expose a specific LLM provider. Model selection and provider-specific request/response translation belong behind future integration ports and adapters. Likewise, repository, CI, and approval providers are not embedded in core contracts; new providers implement the relevant port without requiring project-specific agents or workflows.

## 8. Future Harness² integration
`harness/` is isolated from runtime. `evaluation/` scores agents, `optimization/` tests prompt/skill/tool/config changes, `harness2/` is reserved for the Harness² adapter. Runtime metrics from `core/evaluation/` feed it.

## Decisions & deviations from the proposed tree
- Added `core/contracts/` - without a home for interfaces, Rules 2-5 have nowhere to live.
- Added `integrations/llm/` - Rule 5 (model independence) needs an adapter slot like the other external services.
- The repository had no selected backend language or dashboard directory. Contracts are therefore defined as language-neutral JSON Schema plus port descriptions; the schema-validation test runner is development-only.
- Everything else follows the requested structure.

## Next step
Implement the orchestrator and state machine against the established contracts in a later phase.
