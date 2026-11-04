# Phase 6: Local Orchestrator Implementation and Verification

Date: 2026-11-02

Branch: `phase-6-orchestrator`; base HEAD: `2b22a2d`.
This continuation did not stage, commit, push, install dependencies, call a real
model API, or modify agent checkpoint refs/history.

## 1. Conclusion and acceptance boundary

The local, synchronous orchestration core is implemented and verified:
dispatch, artifact handoff, approval/revision, SQLite persistence and recovery,
bounded retries, task-item scheduling, bounded Fix rework, and observation ports.
All seven agents (including SpecAgent) are exercised through the orchestrator
with fake model/repository/sandbox ports.

This closes the missing core capabilities identified after the first Phase 6
batch, within the decisions below. It is not a production-readiness or live-chain
sign-off, and is not completion of every future architecture/integration target.
Reviewer acceptance remains separate from implementation/test completion.

### Decisions explicitly confirmed by the user

1. SQLite local persistence using the Python standard library, no new dependency.
2. At most three automatic Fix cycles per task item before escalation.
3. Execute items sequentially according to dependsOn, with each CODE still
   relative to the original baseRef, WITHOUT accumulating a workspace.

An explicit operator resume grants a new bounded window; it is not an automatic
extension. Zero Fix budget cannot be resumed. The operator must supply a reason.

### Scope matrix

| Requirement | Implementation | Verification |
|---|---|---|
| Dispatch and artifact routing | Registry, exact consumed types, isolated requests/results | Existing 40 dispatcher cases and actual Spec/Plan approval test |
| Durable restart | SQLite checkpoints with full artifacts/results/progress | Close/reopen tests and a fresh Python process completing Plan |
| Approval atomicity | Store-owned ApprovalRepository plus execution transaction | Injected save failures roll back decisions and new approvals |
| Crash recovery | Committed in-flight marker before dispatch | Simulated process exit; automatic replay rejected |
| Bounded retries | Step retryPolicy, retryable/error-code checks, persisted deadline | Clock/backoff/bounds/restart/nonretryable/cancellation tests |
| Escalation resume | Existing RESUME transition plus trusted operator reason | Approval and Fix escalation/resume tests |
| Task items | Bounded topological order; per-item final artifacts | Dependency validation and two-item actual-agent scenarios |
| Fix loop | Review/Test failures -> Fix -> Review -> Test | No failure, review failure, test failure, both, exhaustion, stale reports |
| Events and metrics | Durable outbox and injected write-side ports | Delivery failure, restart, acknowledgement, reentrancy tests |
| Phase 8 boundary | Injected synchronous action handlers | Missing CI fails; injected fake CI/merge completes default workflow |

These are report-local acceptance groupings derived from the user request and
confirmed decisions, not a claim that a separate Phase 6 specification was approved.

## 2. What the implementation does

### 2.1 Lifecycle and public API

- `start`: creates a run; inputs are keyed by workflow step ID.
- `tick`: dispatches at most one synchronous agent/action call. It does not busy
  wait, sleep, or run downstream agents while approval/retry/escalation is pending.
- `get`: returns an isolated snapshot.
- `decide`: stamps trusted time and delegates reviewer/quorum validation to
  ApprovalService. Rejections carry stored feedback plus the previous artifact
  back to its producer. Expired decisions persist expiry and failed run together.
- `cancel`: cancels the execution and a pending approval.
- `resume`: continues an escalated run with an explicit recorded operator reason.
- `recover`: deals explicitly with interrupted dispatch; default is failure,
  not replay. Retrying requires `retry_interrupted=True`.
- `workflow_run` and `task`: contract-shaped status/stage/artifact projections.
- `flush_observations`: explicit event/metrics delivery to injected sinks.

Definitions and approval/loop policies are pinned in each execution. A different
version, changed steps under the same version, or different policies cannot
silently resume a checkpoint.

### 2.2 Persistence and failure atomicity

SQLite stores execution snapshots, approvals and decisions on the same connection.
The checkpoint includes current artifacts, all accepted artifact history, agent
results, feedback, attempt counters, retry deadlines, task order/item progress,
outbox records and recovery notes.

Dispatch has two local durability boundaries:

1. Commit an in-flight marker before invoking the agent/action.
2. Commit its result, new approval if applicable, observations and workflow
   advancement together.

If dispatch or final checkpoint persistence is interrupted, the original marker
remains. A new process refuses to repeat it automatically. Local rollback cannot
undo provider billing or an external action that completed before the crash.
Explicit recovery documents the operator's decision about possible duplication.

SQLite is behind ExecutionStore; the orchestrator does not import sqlite3.
The adapter exposes ApprovalRepository as part of the same unit of work.

### 2.3 Retry semantics

- `maxAttempts` counts the initial call.
- Only a FAILED result with errors can be retried.
- Every error must be retryable.
- If `retryOn` is supplied, every error code must be in it; an empty list retries
  nothing.
- No retryPolicy means no automatic retry.
- The first wait is backoffSeconds (default zero); subsequent waits double,
  capped at 3,600 seconds.
- Deadlines survive restart; early ticks do not call the agent.
- Event/metrics history retains failed attempts, but a later success does not
  leave those transient errors in terminal run.errors.
- Fix uses the optional `CodeLoopPolicy.fix_retry_policy`. Transport retries
  within one Fix cycle do not consume another rework slot.
- Unknown plugin exceptions, malformed results, quality verdicts and REJECTED
  validation results are not silently reclassified as retryable failures.

Provider-level retries remain the gateway's responsibility and are distinct from
workflow retries. A live composition root must share the configured provider
request budget across agents; this work does not persist or extend Gemini's
provider-request budget.

### 2.4 Code loop and multi-item execution

Enable the loop explicitly with CodeLoopPolicy. This preserves the first batch's
fail-closed behavior for callers not opting into automatic rework.

```text
Implement -> Review APPROVE -> Test PASS -> next dependency-ready item / next step
                  |                 |
           CHANGES_REQUESTED        FAIL
                  +-------> Fix ----+
                              |
                           Review -> Test
```

For each item:

- The original baseRef is retained. Conflicting refs in per-step input are rejected.
- Reports must match current CODE ID/version, item ID and upstream metadata.
- Verdict in report content must agree with the result verdict.
- Replacement CODE increments version and identifies the replaced CODE.
- Successful replacement clears the CURRENT review/report inputs; old evidence
  remains in history, so stale evidence is not fed into another Fix.
- Three Fix cycles are allowed by default, then execution waits in
  CODE_FIX_ESCALATED.
- The next item is selected only after both Review and Test pass. Its Fix budget
  starts fresh; another item's CODE/report inputs do not leak into its request.

The graph extension uses existing StageGraph/RunState/apply behavior and existing
triggers; it does not change the generic state-machine transition implementation.
TASK parsing reuses TaskContent/TaskItem and the existing task count limit.

### 2.5 Events, metrics and integration boundary

Agent events and metrics results are retained in a durable outbox, alongside
workflow start/stage/retry/rework/resume/recovery/cancel/completion events.
Delivery is at-least-once. Sinks deduplicate by event.id / result.request_id.
Acknowledgements survive restart. Missing sinks leave records pending, rather than
pretending delivery succeeded. Sink exceptions surface with a safe message and do
not erase the pending record. Recursive dispatch from callbacks is rejected.

MetricsRecorder is the write-side subset of the existing MetricsService concept,
not Phase 10 aggregate analytics/evaluation.

The default workflow still contains CI/merge. Missing handlers produce
INTEGRATION_UNAVAILABLE. Tests inject fake action handlers to prove the sequencing
boundary; there is no real GitLab, CI, Teams or merge operation.

## 3. Test inventory and preservation

| Test file | Collected cases |
|---|---:|
| tests/unit/test_orchestrator.py | 40 |
| tests/unit/test_orchestrator_code_loop.py | 24 |
| tests/unit/test_orchestrator_operations.py | 22 |
| tests/integration/test_orchestrator_chain.py | 1 |
| tests/integration/test_orchestrator_rework.py | 20 |
| Total Phase 6 | 107 |

- Previous full-suite baseline: 961 tests, 404 subtests.
- Current full suite: 1,027 tests, 404 subtests; 66 additional cases in this continuation.
- Relative to the pre-Phase-6 base: 920 + 107 = 1,027.
- No failures, skips or xfails reported by the final suite.
- No tracked test file from Phase 7 was changed.
- One initial-batch Phase 6 test intentionally changed:
  `test_configured_retry_policy_is_rejected_rather_than_ignored` became
  `test_configured_retry_policy_is_executed_without_extra_calls_on_success`.
  The old assertion represented an unimplemented feature. It is replaced by
  positive dispatch/count/deadline assertions, with separate bounds, allowlist,
  failure, cancellation and restart tests. Other first-batch cases remain.
- No new noqa, type-ignore or nosec suppression. Bandit retains the pre-existing
  single disabled finding.

Important proof cases include:

- `test_fresh_python_process_resumes_quorum_and_runs_plan_without_repeating_spec`
- `test_decision_and_execution_checkpoint_roll_back_together`
- `test_result_and_new_approval_roll_back_but_inflight_checkpoint_survives`
- `test_crash_recovery_never_replays_without_explicit_operator_acceptance`
- `test_retry_schedule_respects_clock_allowlist_bounds_and_restart`
- `test_actual_agents_complete_bounded_rework_and_preserve_links`
- `test_three_fixes_max_then_persisted_escalation_and_explicit_resume`
- `test_fix_budget_is_per_item_and_resets_only_after_passing_review_and_test`
- `test_restart_after_failed_report_does_not_reuse_stale_review_or_report`
- `test_event_and_metrics_outbox_survives_failure_and_restart`

Selected statement coverage: 97%, 695 statements, 19 missing. Code-loop and
registry modules are at 100%; engine and SQLite adapter at 97%.
Coverage is not proof of semantic parity, fault-free behavior or security.

## 4. Gate results

All Python commands used `.\.venv\Scripts\python.exe`.

| Gate | Result | Exit |
|---|---|---:|
| pytest tests -x -q | 1,027 passed, 404 subtests passed | 0 |
| mypy src --strict | Success, 95 source files | 0 |
| Ruff src tests | All checks passed | 0 |
| Bandit -r src | No findings; one pre-existing disabled issue | 0 |
| TODO/FIXME in Implement + Orchestrator Python | No matches | 1 |
| Focused Phase 6 tests + coverage | 107 passed, 97% statement coverage | 0 |
| Pylance syntax, engine.py and storage/sqlite.py | No syntax errors | n/a |
| Worktree credential-literal pattern scan | 0 matching lines; locations/counts only | 0 |
| git diff --check | No whitespace errors | 0 |
| Port documentation contract test | 1 passed, 20 subtests passed | 0 |

Exit 1 for ripgrep means no matches, not a failing quality gate.
The supplied prior credential-literal pattern is checked separately against
tracked/untracked non-ignored worktree files, reporting locations/counts only.
This is not a claim that all Git history is clean or that push protection is resolved.
Final Git verification: 0 staged files; branch and HEAD remain
phase-6-orchestrator / 2b22a2d.

## 5. Raw final gate output

### pytest

```text
............................................................. [  5%]
.................................. [  9%]
............................................................................ [ 16%]
............................ [ 19%]
........................................................................ [ 26%]
........................................................................ [ 33%]
.................................................................... [ 40%]
........................................................................................................................ [ 51%]
........................................................................ [ 58%]
........................................................................ [ 65%]
............................................................................................. [ 74%]
........................................................................ [ 81%]
........................................................................ [ 88%]
........................................................................ [ 95%]
...........................................          [100%]
1027 passed, 404 subtests passed in 12.80s
PYTEST_EXIT=0
```

### mypy

```text
Success: no issues found in 95 source files
MYPY_EXIT=0
```

### Ruff

```text
All checks passed!
RUFF_EXIT=0
```

### Bandit

```text
[main]	INFO	profile include tests: None
[main]	INFO	profile exclude tests: None
[main]	INFO	cli include tests: None
[main]	INFO	cli exclude tests: None
[main]	INFO	running on Python 3.13.5
Working... ---------------------------------------- 100% 0:00:00
Run started:2026-11-02 08:09:10.515041+00:00

Test results:
	No issues identified.

Code scanned:
	Total lines of code: 8101
	Total lines skipped (#nosec): 0
	Total potential issues skipped due to specifically being disabled (e.g., #nosec BXXX): 1

Run metrics:
	Total issues (by severity):
		Undefined: 0
		Low: 0
		Medium: 0
		High: 0
	Total issues (by confidence):
		Undefined: 0
		Low: 0
		Medium: 0
		High: 0
Files skipped (0):
BANDIT_EXIT=0
```

### TODO/FIXME

Command:

```powershell
rg -n 'TODO|FIXME' src\asf\agents\implement src\asf\orchestrator -g '*.py'
```

```text
TODO_SEARCH_EXIT=1
```

## 6. Files in the Phase 6 change set

Includes the initial uncommitted batch as well as this continuation:

| File | Change |
|---|---|
| src/asf/orchestrator/registry.py | Typed agent port and unambiguous registration/lookup |
| src/asf/orchestrator/engine.py | Dispatch, durable lifecycle, retries, approvals, code loops, projections and delivery |
| src/asf/orchestrator/execution.py | Validated serializable snapshots and observation records |
| src/asf/orchestrator/code_loop.py | Explicit loop policy, graph extension and dependency validation |
| src/asf/orchestrator/ports.py | Storage unit of work and event/metrics sink protocols |
| src/asf/orchestrator/__init__.py | Public exports |
| src/asf/storage/sqlite.py | Local SQLite execution and approval adapters |
| tests/unit/test_orchestrator.py | Initial dispatch/approval/failure cases, updated retry acceptance case |
| tests/unit/test_orchestrator_code_loop.py | Dependency and loop-configuration cases |
| tests/unit/test_orchestrator_operations.py | Durable restart/atomicity/retry/outbox/action cases |
| tests/integration/test_orchestrator_chain.py | Actual Spec/Plan agents through approval |
| tests/integration/test_orchestrator_rework.py | Actual seven-agent rework and multi-item orchestration |
| src/asf/orchestrator/README.md | Public API, usage, recovery and exact limits |
| src/asf/storage/README.md | SQLite lifecycle, transaction and data-retention boundary |
| src/asf/agents/README.md | Distinguish Phase 7 direct chains from Phase 6 orchestration tests |
| contracts/ports.md | Document local checkpoint port and write-side metrics delivery |
| docs/architecture/README.md | Replace obsolete not-implemented status |
| docs/architecture/phase-7-code-agents.md | Record the agreed non-cumulative multi-item deviation |
| README.md | Current implementation status |
| docs/PHASE_6_REPORT.md | This requested report |

Existing untracked debug/backup files and docs/scripts content were left untouched.
The Git index remains empty. No additional Phase 6 commit was created.

## 7. Commands for reviewer verification

Run from the repository root in PowerShell:

```powershell
# All Phase 6 cases, including real agent classes with fake ports.
$files = @(Get-ChildItem tests\unit\test_orchestrator*.py, tests\integration\test_orchestrator*.py | ForEach-Object FullName)
.\.venv\Scripts\python.exe -m pytest @files -v

# Full regression and existing quality gates.
.\.venv\Scripts\python.exe -m pytest tests\ -x -q
.\.venv\Scripts\python.exe -m mypy src\ --strict
.\.venv\Scripts\python.exe -m ruff check src\ tests\
.\.venv\Scripts\python.exe -m bandit -r src\
rg -n 'TODO|FIXME' src\asf\agents\implement src\asf\orchestrator -g '*.py'

# Selected statement coverage.
.\.venv\Scripts\python.exe -m pytest @files -q --cov=asf.orchestrator --cov=asf.storage.sqlite --cov-report=term-missing
```

The fresh-process test uses the same virtualenv Python executable and fake model
gateway; it neither calls the provider nor executes generated code.

See the [orchestrator usage guide](../src/asf/orchestrator/README.md) for composing
an actual local run with injected ports and a private SQLite path.

## 8. Limits, deviations and work not performed

1. **No live-chain claim.** All model/repository/sandbox operations in tests are
   fake-backed. Real adapter composition, actual generated-code execution and
   real provider latency/billing remain unverified.
2. **No cumulative workspace.** This is the explicit user decision. dependsOn
   orders execution but does not make T1's generated files available to T2.
   The earlier architecture target of applying changes between tasks is not met
   by this local mode and is documented as a live-integration target.
3. **No aggregate CI changeset.** The default workflow tail sees the last item's
   current artifacts. An aggregate workspace/commit policy must be agreed before
   multi-item live CI/merge. Previous item artifacts remain inspectable.
4. **One synchronous local worker.** SQLite holds a write transaction during
   dispatch finalization, including the agent call. Other writers can receive
   SQLITE_BUSY. No leases, distributed workers, job queue or concurrent scheduler.
5. **No preemptive cancellation/deadline.** Step timeout is checked after return;
   adapters must enforce their own deadlines. Recovery is not exactly-once
   provider/external execution.
6. **Outbox is at-least-once.** A crash after sink delivery but before local
   acknowledgement can redeliver. Consumer deduplication is required.
7. **Storage is not encrypted/redacted evidence.** It retains original application
   input/context/content. Credentials must remain in environment-backed adapters,
   never execution context. Use a private path under ignored artifacts.
8. **Checkpoint port, not every CRUD repository.** Complete local execution data
   is durable; schema-shaped Task/WorkflowRun projections are provided. This does
   not implement all standalone repository interfaces from the general port catalog.
9. **Trusted operator APIs.** resume/recover do not authenticate a remote user.
   Backend authorization, user-facing approvals, CLI/service hosting and automatic
   skill-file resolution are not added by this core-library change.
10. **Phase 8/9/10 remain separate.** No real GitLab/CI/Teams, backend-connected
    dashboard, aggregate metrics/evaluation or deployment was implemented.
11. **Earlier debt remains unchanged.** Approved C2 deviations and historical
    credential/push-protection concerns are not resolved or rewritten here.

Recommended acceptance: review this report and run the commands above to accept
the **local Phase 6 core scope**, while keeping the listed live-integration and
operational targets explicitly open.
