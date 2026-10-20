# Core contracts

Core contracts are the technology-independent data formats and ports shared by the orchestrator, workflows, agents, approvals, integrations, and evaluation. The canonical data definitions are in [`schemas/contracts.schema.json`](schemas/contracts.schema.json), using JSON Schema Draft 2020-12. They are serializable JSON and can be validated before being passed over REST, WebSocket/SSE, message queues, event buses, or persisted by an adapter. The schemas do not choose an implementation language, storage system, transport, or provider.

## Contracts

The schema defines:

- `AgentMetadata` and `AgentStatus` for an agent's identity, version, capabilities, configuration, and lifecycle status.
- `AgentRequest` and `AgentResult` for standardized invocation and response, including output, artifacts, activity events, metrics, and errors.
- `Artifact` for versioned content or an opaque external storage reference. Common artifact types include `SPEC`, `PLAN`, `TASK`, `CODE`, `CODE_REVIEW`, and `TEST_REPORT`; custom types are accepted.
- `Task` and `Workflow` / `WorkflowStep` for project-independent work and declarative workflow definitions.
- `ApprovalRequest` and `ApprovalDecision` for human review, including `REQUEST_CHANGES` and reviewer comments.
- `ActivityEvent` for observable platform activity, including the standard task, agent, artifact, approval, test, CI, and workflow events. Custom event types are accepted.
- `AgentMetrics`, `Project`, and `PlatformError` for shared metrics, project configuration, and error reporting.

Rates are fractions from 0 through 1; `averageExecutionTime` is measured in seconds. Metadata/configuration fields are JSON objects intended for producer-owned extensions. The contract enums deliberately distinguish closed lifecycle values from extensible type/event names.

## Agent communication

Agents receive an `AgentRequest`, validate it, and execute it to return an `AgentResult`. They do not call or sequence other agents, nor depend directly on GitLab, Teams, a dashboard, a database, or an LLM provider. The `Agent` port and repository/service ports are documented in [`ports.md`](ports.md); they specify required capabilities without binding them to a language or adapter.

The orchestrator controls workflow progression. An agent returns output and artifacts; the orchestrator stores or resolves the artifacts and makes relevant artifacts available to the next step. Agents therefore communicate indirectly through workflow-managed artifacts, rather than through tightly coupled calls. Artifact content can travel inline or through an opaque repository reference, allowing large content to live outside an agent process.

## Approval and feedback

When a workflow step requires human review, the platform creates an `ApprovalRequest` associated with its project, task, workflow, and artifact. An `ApprovalDecision` records the reviewer, decision, timestamp, and feedback comment. `REQUEST_CHANGES` or `REJECTED` returns control to the orchestrator, which can include the feedback in a later `AgentRequest`; the approval service itself does not revise artifacts or call agents.

## Events and dashboard

An agent or platform component can emit `ActivityEvent` records through the `EventPublisher` port. Events are transport-neutral and include the project/task/workflow/agent correlation fields, timestamp, type, message, and extensible metadata. A future dashboard can subscribe through an adapter backed by WebSocket/SSE or another transport; the same events can also feed logging, evaluation, and audit systems. No dashboard backend or real-time transport is part of these contracts.

## Projects and providers

`Project` captures repository and technology information, enabled agents/skills, workflow selection, configuration, and status without hard-coding VHPC, VNPC, or another project. Existing YAML profiles are configuration sources; a future configuration layer can map them to this normalized contract.

Agents receive context and artifacts through the same request contract regardless of which LLM, repository, CI system, or approval channel is configured. Provider-specific behavior belongs behind ports and adapters in `integrations/`, so switching providers does not change the agent or workflow data contracts.

## Validation

The unit tests in `tests/unit/test_contracts.py` validate representative accepted and rejected instances for each data contract against the schema. Test tooling is declared in the repository-root `requirements-dev.txt`; it is not a runtime dependency of the platform.
