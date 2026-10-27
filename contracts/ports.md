# Core ports

These are language-neutral port descriptions, not implementations. Implementations belong in the core or in adapters, and must use the data contracts in `schemas/contracts.schema.json`. Methods that return collections return an empty collection when there are no matches; missing single resources return a not-found error.

| Port | Operations |
|---|---|
| `Agent` | `getMetadata() -> AgentMetadata`; `validate(request: AgentRequest) -> ValidationResult`; `execute(request: AgentRequest) -> AgentResult` |
| `AgentRegistry` | `get(agentId) -> Agent`; `list() -> AgentMetadata[]`; `register(agent)`; `unregister(agentId)` |
| `ArtifactRepository` | `create(artifact: Artifact) -> Artifact`; `get(artifactId) -> Artifact`; `listByTask(taskId) -> Artifact[]` |
| `TaskRepository` | `create(task: Task) -> Task`; `get(taskId) -> Task`; `update(task: Task) -> Task`; `listByProject(projectId) -> Task[]` |
| `WorkflowRepository` | `get(workflowId) -> Workflow`; `list() -> Workflow[]` |
| `WorkflowRunRepository` | `create(run: WorkflowRun) -> WorkflowRun`; `get(runId) -> WorkflowRun`; `getByTask(taskId) -> WorkflowRun`; `update(run: WorkflowRun) -> WorkflowRun`; `listByProject(projectId) -> WorkflowRun[]` |
| `ApprovalRepository` | `create(approval: ApprovalRequest) -> ApprovalRequest`; `get(approvalId) -> ApprovalRequest`; `update(approval: ApprovalRequest) -> ApprovalRequest`; `listByTask(taskId) -> ApprovalRequest[]`; `listPending() -> ApprovalRequest[]`; `addDecision(decision: ApprovalDecision)`; `listDecisions(approvalId) -> ApprovalDecision[]` |
| `ApprovalService` | `request(taskId, workflowId, projectId, artifactId, type, requestedBy, policy: ApprovalPolicy, metadata, now) -> ApprovalRequest`; `get(approvalId) -> ApprovalRequest`; `decide(decision: ApprovalDecision) -> ApprovalRequest`; `cancel(approvalId, now) -> ApprovalRequest`; `expireDue(now) -> ApprovalRequest[]`; `listDecisions(approvalId) -> ApprovalDecision[]`; `feedbackFor(approvalId) -> ApprovalFeedback[]` |
| `EventPublisher` | `publish(event: ActivityEvent)` |

| `MetricsService` | `record(agentId, result: AgentResult)`; `getAgentMetrics(agentId) -> AgentMetrics` |
| `ProjectRepository` | `get(projectId) -> Project`; `list() -> Project[]` |
| `ModelGateway` | `complete(request: ModelRequest) -> ModelResponse` |
| `SourceControl` | `createBranch(projectId, branch, baseRef)`; `commit(projectId, branch, message, files: map<path, content>)`; `openChangeRequest(projectId, sourceBranch, targetBranch, title, description) -> CodeChangeRequest`; `getChangeRequest(projectId, changeRequestId) -> CodeChangeRequest` |
| `CiProvider` | `trigger(projectId, ref) -> PipelineRun`; `getRun(projectId, runId) -> PipelineRun` |

`ValidationResult` is defined in the schema as `{ valid: boolean, errors: PlatformError[] }`. A validation failure is an ordinary result, not an execution; `execute` returns `AgentResult` and does not dispatch another agent.

Operations that depend on time obtain time only from a `now` argument, the payload, or an injected clock, never by reading a clock themselves; `ApprovalDecision.createdAt` is stamped by the caller from a trusted clock.

### Errors

A missing single resource returns a `PlatformError` with code `NOT_FOUND`; all ports report failures with `PlatformError` using codes from [`errors.md`](errors.md).

The platform must not depend on a concrete persistence, transport, notification, source-control, or model provider through these ports. For example, an `ApprovalService` adapter may later use Teams, Slack, or a web UI, while an `EventPublisher` adapter may feed an in-memory observer, WebSocket/SSE, or a message queue.
