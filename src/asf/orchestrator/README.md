# Workflow orchestration

The orchestrator is the only component that sequences agents. Agents do not call
one another and do not own approval or workflow transitions.

## Supported Phase 6 behavior

- Registry lookup by ID/type; ambiguous registrations are rejected.
- `start`: independent execution, with input keyed by workflow step ID.
- `tick`: at most one synchronous agent/action call; exact consumed artifacts,
  result identity/output checks and state-machine transitions.
- ApprovalService reviewer/quorum, rejection feedback, revision limits, expiry,
  cancellation and explicit escalation `resume`.
- Optional persistent store (MariaDB for real runs, in-memory for tests)
  with execution/approval transaction boundaries,
  pinned workflow definitions/policies and restart without replay of completed work.
- Retryable FAILED results can be retried under the step's `retryPolicy`.
  `maxAttempts` includes the first call. `retryOn`, when supplied, must match every
  returned error; every error must also be retryable. Missing policy means no retry.
  Exponential delay starts at `backoffSeconds` (default zero) and is capped at
  3,600 seconds. `tick` never sleeps; it returns without dispatch before `retry_at`.
- Optional `CodeLoopPolicy`: Implement -> Review -> Test for each dependency-ready
  task item. CHANGES_REQUESTED/FAIL routes through Fix -> Review -> Test again.
  Three automatic Fix slots per item by default, then WAITING escalation.
  Transport retries of a Fix use `fix_retry_policy` and do not take a second slot.
- Successful CODE replacements clear current review/report inputs; old artifacts
  remain in history. Reports must match the current code ID/version and task.
- Task items are bounded by the TaskAgent count limit, ordered topologically and
  executed sequentially. Unknown dependencies, duplicate IDs and cycles fail.
- Durable event and agent-result metrics outbox. Call `flush_observations` to
  deliver to injected `EventPublisher`/`MetricsRecorder` ports. Failed delivery
  raises explicitly and remains pending. Delivery is at-least-once; consumers
  deduplicate by `event.id` and `result.request_id`. No sink means pending, not
  silently delivered. This is wiring, not Phase 10 evaluation/analytics.
- Injected synchronous action handlers provide the Phase 8 boundary. An absent
  CI/merge handler fails with INTEGRATION_UNAVAILABLE; it never simulates success.

## Constructing a local persistent run

Use existing agent factories to populate a registry. Each agent must receive
injected model/repository/sandbox ports. A caller supplies an aware clock and
globally unique IDs, including across restarts.

```python
from asf.approval.models import ApprovalPolicy
from asf.orchestrator import CodeLoopPolicy, Orchestrator
from asf.storage.memory import InMemoryStore

# definition and registry are prepared by the composition root.
# The artifacts directory must exist and must not be committed.
store = InMemoryStore()  # tests; real runs use MariaDbExecutionStore
engine = Orchestrator(
    definition,
    registry,
    clock=clock,
    new_id=new_id,
    store=store,
    approval_policy=ApprovalPolicy(reviewers=["reviewer"]),
    code_loop=CodeLoopPolicy(max_fixes=3, all_task_items=True),
)
run = engine.start(
    task_id="work-1",
    project_id="project-1",
    inputs={
        "spec": {"requirement": "Describe the feature"},
        "implement": {"ref": "base-ref"},
    },
    context={"project": {"testCommands": [["pytest", "-q"]]}},
)
run = engine.tick(run.id)
# If run.approval_id is set, wait for a trusted operator:
# run = engine.decide(run.id, reviewer="reviewer", decision="APPROVED")
# Reconstruct engine with the same definition/policies and store to restart:
# run = engine.get(saved_run_id)
store.close()
```

`CodeLoopPolicy` is explicit to preserve the initial dispatcher's fail-closed
behavior for callers that do not enable automatic rework. Use
`all_task_items=False` plus `inputs["implement"]["taskItemId"]` to run only one
selected item. Task item IDs are managed by the loop; base refs cannot conflict.

`workflow_run(run_id)` and `task(run_id)` return contract-shaped projections.
All successful artifacts, including superseded revisions and all task items,
remain in `artifact_history` and in the Task projection. Passing final reports
are available per item in `item_results`.

## AI review loop (Phase 12)

Gated steps whose resolved approval mode is `ai` are decided by the
`artifact-review` agent instead of a human (`ai_review.py` claims the
`X_REVIEW` stage, `ai_review_apply.py` applies the result). The verdict
is computed in code from the findings, never taken from the model.
Each round is keyed by (run, stage, revision) and persisted as an
`ARTIFACT_REVIEW` artifact plus `AI_REVIEW_STARTED` /
`AI_REVIEW_COMPLETED` events, so a restart mid-loop resumes without
duplicating a round.

- Escalation reasons: `MAX_REVISIONS` (revision budget exhausted),
  `NO_PROGRESS` (stagnation: the set of open blocking findings did not
  shrink), `REVIEWER_FAILED` (the reviewer errored past its bounded
  retry — never converted into an approval), `BUDGET` (the run's
  review-round budget ran out).
- **Exhaustion is evaluated before stagnation**: on the final allowed
  round the escalation reason is `MAX_REVISIONS` even if the blockers
  also did not shrink. Stagnation is only the early stop while
  revisions remain. On exhaustion the project's `onExhausted` decides:
  `escalate` (default) or `accept_with_warnings`.
- Manual override: an ai-mode request is addressed to `ai-reviewer`
  plus the profile's human reviewers, so a human approve/reject is
  allowed at any point; it is recorded with `reviewer_kind` HUMAN and
  wins over an in-flight AI round (the apply path re-checks that the
  request is still PENDING before applying an AI result).
- Escalated gates: Resume restarts the revision window and may carry
  an operator guidance comment, delivered to the producer as human
  feedback. "Approve anyway" (`gate_ops.approve_anyway`) records a
  fresh approval request decided APPROVED by the operator and takes
  the `ESCALATED --APPROVED--> APPROVED` graph edge; the edge is
  additive, so runs pinned to pre-Phase-12 definitions are unaffected
  unless the operator invokes it.

Operator-facing reference (sequence, configuration, troubleshooting):
`docs/ai-review-approval.md`.

## Recovery and operational boundaries

- An in-flight marker is committed BEFORE dispatch. If dispatch/finalization is
  interrupted, `tick` refuses replay. `recover(run_id, reason=...)` defaults to
  failing the interrupted run. `retry_interrupted=True` explicitly accepts
  possible duplicate provider charges/external execution. Exactly-once external
  effects cannot be promised by a local database.
- `resume(run_id, reason=...)` grants a new bounded revision/Fix window after
  escalation. This is a trusted-operator API, not automatic unlimited rework.
  A zero Fix budget cannot be resumed. Reasons are retained in the checkpoint.
- Definitions and approval/loop policies are pinned in each execution. Reusing an
  ID/version with changed steps is also rejected. There is no silent migration.
- Use one local synchronous worker. No threads, leases, process scheduler or
  preemptive cancellation. A step timeout is checked after return; provider and
  sandbox adapters must enforce their own request/command deadlines.
- Every task item's CODE remains relative to the original `baseRef`. Dependency
  ordering does NOT accumulate a workspace or prove multi-item integration.
  The existing default CI/merge tail receives the last item's current artifacts;
  an aggregate workspace/commit policy must be agreed before live Phase 8 use.
- The execution store retains original application content. Keep credentials in
  environment-backed adapters, never execution context. See the storage README.
- Running the engine without a store remains useful for tests but does not
  make approval/execution changes atomic across failures. Use the store-owned
  approval service in durable mode; supplying an unrelated ApprovalService is
  rejected.
- No real repository/sandbox adapter, real model-backed chain, GitLab/CI/Teams,
  backend API, distributed scheduler or Phase 10 analytics is implemented here.

## Verification

```powershell
$files = @(Get-ChildItem tests\unit\test_orchestrator*.py, tests\integration\test_orchestrator*.py | ForEach-Object FullName)
.\.venv\Scripts\python.exe -m pytest @files -v
```

Tests drive the actual Spec, Plan, Task, Implement, Review, Test and Fix agents
with scripted model responses and sandbox results; no real API/process execution.
