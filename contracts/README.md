# Core contracts

Core contracts are the technology-independent data formats and ports shared by the orchestrator, workflows, agents, approvals, integrations, and evaluation. The canonical data definitions are in [`schemas/contracts.schema.json`](schemas/contracts.schema.json), using JSON Schema Draft 2020-12. They are serializable JSON and can be validated before being passed over REST, WebSocket/SSE, message queues, event buses, or persisted by an adapter. The schemas do not choose an implementation language, storage system, transport, or provider.

> **Note:** Contracts are pre-1.0; breaking changes are allowed until the orchestrator (Phase 6) consumes them.

## Contracts

The schema defines:

- `AgentMetadata` and `AgentStatus` for an agent's identity, version, capabilities, configuration, and lifecycle status.
- `AgentRequest` and `AgentResult` for standardized invocation and response, including output, artifacts, activity events, per-run `RunMetrics`, and errors.
- `RunMetrics` for single-run execution metrics (`durationSeconds`, `revisionCount`, `attempt`) returned in `AgentResult`.
- `AgentMetrics` for aggregate agent performance statistics (`totalTasks`, success/approval rates, average execution time) aggregated and returned by `MetricsService.getAgentMetrics`.
- `Artifact` for versioned content or an opaque external storage reference. Common artifact types include `SPEC`, `PLAN`, `TASK`, `CODE`, `CODE_REVIEW`, and `TEST_REPORT`; custom types are accepted.
- `Task` (including fine-grained workflow `Task.stage` owned by the state machine), `Workflow` / `WorkflowStep` for declarative, project-independent workflow definitions, and `WorkflowRun` for tracking a single execution of a workflow definition.
- `ApprovalPolicy`, `ApprovalRequest`, `ApprovalDecision`, and `ApprovalFeedback` for human review, with extensible request types (`SPEC`, `PLAN`, `TASK`, `CODE_REVIEW`, `DEPLOYMENT`, or custom) and request status tracking (`PENDING`, `APPROVED`, `REJECTED`, `CHANGES_REQUESTED`, `CANCELLED`, `EXPIRED`).
- `ActivityEvent` for observable platform activity, including the standard task, agent, artifact, approval, test, CI, and workflow events. Custom event types are accepted.
- `ModelRequest` and `ModelResponse` for language-model gateway interactions independent of specific LLM providers.
- `CodeChangeRequest` for tracking branches and change requests across source control systems.
- `PipelineRun` for tracking continuous integration builds and test pipelines.
- `Project` and `PlatformError` for shared project configuration and standardized error reporting (with codes documented in [`errors.md`](errors.md)).

> **Identity rule (W2):** In `Task`, `AgentRequest`, `ApprovalRequest`, and `ActivityEvent`, the `workflowId` field identifies the workflow DEFINITION. A task has at most one execution `WorkflowRun` (`WorkflowRun.taskId`).

Rates are fractions from 0 through 1; `averageExecutionTime` and `durationSeconds` are measured in seconds. Metadata/configuration fields are JSON objects intended for producer-owned extensions. The contract enums deliberately distinguish closed lifecycle values from extensible type/event names.


## Agent communication

Agents receive an `AgentRequest`, validate it, and execute it to return an `AgentResult`. They do not call or sequence other agents, nor depend directly on GitLab, Teams, a dashboard, a database, or an LLM provider. The `Agent` port and repository/service ports are documented in [`ports.md`](ports.md); they specify required capabilities without binding them to a language or adapter.

The orchestrator controls workflow progression. An agent returns output and artifacts; the orchestrator stores or resolves the artifacts and makes relevant artifacts available to the next step. Agents therefore communicate indirectly through workflow-managed artifacts, rather than through tightly coupled calls. Artifact content can travel inline or through an opaque repository reference, allowing large content to live outside an agent process.

## Approval and feedback

When a workflow step requires human review, the platform creates an `ApprovalRequest` associated with its project, task, workflow, and artifact. An `ApprovalPolicy` defines `minApprovals`, authorized `reviewers` (opaque identifier strings), and optional `expiresInSeconds`. When creating a request, `minApprovals` and `reviewers` are snapshotted onto the `ApprovalRequest`, and `expiresAt` is set to `now + expiresInSeconds` (or `null` if none).

An `ApprovalDecision` records the reviewer, decision (`APPROVED`, `REJECTED`, `REQUEST_CHANGES`), timestamp, and feedback comment. Decisions follow strict lifecycle rules:
- **Distinct-approvals rule**: An `APPROVED` decision must come from an authorized reviewer who has not already approved. When the count of distinct approving reviewers reaches `minApprovals`, the request status becomes `APPROVED`; otherwise, it remains `PENDING`.
- **Status mapping**: `APPROVED -> APPROVED` (once `minApprovals` are met); `REJECTED -> REJECTED` immediately; `REQUEST_CHANGES -> CHANGES_REQUESTED` immediately.
- **Expiry**: Handled explicitly via `expireDue(now)` (or lazily upon decision at or after `expiresAt`), which transitions past-due pending requests to `EXPIRED`.
- **Feedback**: Stored negative decisions (`REJECTED` or `REQUEST_CHANGES`) produce `ApprovalFeedback` records via `feedbackFor(approvalId)`. The `AgentRequest.feedback` field replaces the earlier `input.feedback` convention, allowing the orchestrator to pass reviewer feedback directly when re-invoking the producing agent. The approval service itself does not revise artifacts or call agents.

## Events and dashboard

An agent or platform component can emit `ActivityEvent` records through the `EventPublisher` port. Events are transport-neutral and include the project/task/workflow/agent correlation fields, timestamp, type, message, and extensible metadata. A future dashboard can subscribe through an adapter backed by WebSocket/SSE or another transport; the same events can also feed logging, evaluation, and audit systems. No dashboard backend or real-time transport is part of these contracts.

## Projects and providers

`Project` captures repository and technology information, enabled agents/skills, workflow selection, configuration, and status without hard-coding any specific project. Existing YAML profiles are configuration sources; a future configuration layer can map them to this normalized contract.

Agents receive context and artifacts through the same request contract regardless of which LLM, repository, CI system, or approval channel is configured. Provider-specific behavior belongs behind ports and adapters in `src/asf/integrations/` and `src/asf/models/providers/`, so switching providers does not change the agent or workflow data contracts.

## Validation

The unit tests in `tests/unit/test_contracts.py` validate representative accepted and rejected instances for each data contract against the schema. Test tooling is declared in the repository-root `pyproject.toml` (and `-e .[dev]` in `requirements-dev.txt`); it is not a runtime dependency of the platform.
