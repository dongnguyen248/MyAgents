# Phase 7 C3-C5 Implementation and Verification Report

Date: 2026-11-02

Branch: `phase-7-agents`; HEAD: `efbaeb9`.
Results cover the current worktree, including pre-existing staged changes,
not only HEAD. This task did not stage, commit, push, rewrite history, install
dependencies, call a real model API, or change the Gemini adapter.

## 1. Scope and acceptance boundary

Implemented the remaining Phase 7 agent packages:

- C3: ReviewAgent.
- C4: deterministic TestAgent.
- C5: FixAgent.
- Added fake-driven chain validation through review, test, fix and recheck.

Design reference: [Phase 7 decisions](architecture/phase-7-code-agents.md).
The existing C2 contract was retained following the user's explicit decision
to close C3-C5 and report the C2 differences rather than change its assertions.

All six Phase 7 agents now have implementations: Plan, Task, Implement, Review,
Test and Fix. This means agent logic and injected-port tests exist. It does NOT
mean a real repository/sandbox pipeline, orchestrator, deployment, or operational
security sign-off is complete.

## 2. Implemented behavior

### ReviewAgent

- Requires exactly one linked SPEC, PLAN, TASK and CODE for the selected task.
- Validates CODE with the shared ChangeSet model and checks upstream links.
- Calls only the injected ModelGateway, with provider-neutral packaged prompts.
- Validates findings, severity, optional positive line number, non-whitespace
  strings, supported verdicts and the maximum of 100 findings.
- Rejects APPROVE with ERROR findings and findings outside CODE change paths.
- Enforces raw-reply and rendered-text bounds.
- Produces CODE_REVIEW with JSON review data, Markdown and injected CODE/upstream
  traceability; exposes the verdict without importing state-machine triggers.
- Invalid generated output is FAILED/LLM_INVALID_RESPONSE, non-retryable.

### TestAgent

- Requires linked TASK/CODE and a unique selected task item.
- Does not call an LLM or generate test commands.
- Executes only context.project.testCommands through the injected SandboxPort.
  Task verificationHint and CODE/model text are not command sources.
- Validates command count and argv, including executable path restrictions.
- Uses the CODE baseRef, so the sandbox receives the complete ChangeSet relative
  to the original base.
- Validates sandbox result count/types and handles exceptions/timeouts explicitly.
- Redacts output using the shared detector before UTF-8 byte truncation.
- Builds TEST_REPORT content as:

  ```text
  {format: json, report: {commands, verdict, summary}, text: ...}
  ```

- A nonzero test exit, including exit 5, yields SUCCESS with verdict FAIL.
- Infrastructure failure yields FAILED/SANDBOX_ERROR; timeout yields
  FAILED/COMMAND_TIMEOUT.

### FixAgent

- Requires SPEC/PLAN/TASK, one CODE, and at least one CODE_REVIEW/TEST_REPORT.
- Rejects stale CODE ID/version, another task's reports, duplicate reports,
  mismatched baseRef, malformed expectedFiles and unsupported request context.
- Reads original files through RepositoryPort; never applies changes itself.
- Gives the model previous CODE plus linked review/test evidence as untrusted data.
- Produces a COMPLETE replacement ChangeSet relative to the original baseRef.
- Reuses ImplementAgent's extracted scope, denied-path, size, base-existence and
  secret checks. There is no ImplementAgent/FixAgent inheritance.
- Increments CODE version and injects revisionOf, fixedReviewIds,
  fixedTestReportIds and all upstream IDs/versions.
- Repository errors are REPOSITORY_ERROR; oversized base input is
  REJECTED/VALIDATION_FAILED before the model call.
- Does not expose validation payloads or detected credential values in errors.

### Shared runtime

- AgentExecutionError preserves expected agent/port error code, category and
  retryability without expanding provider-only ModelGateway error codes.
- Preflight REJECTED errors produce no artifacts or lifecycle events.
- Shared input checks cover task identity, artifact versions/content, context
  sizes, attempts, CODE ChangeSet validity and upstream traceability.
- Legacy shared content dataclasses remain compatible; Review payload validation
  lives in the Review package, and Test reports are built from validated results.

## 3. Test inventory

Baseline provided and verified before this work: 708 tests, 404 subtests.

| Added file | Collected cases | Purpose |
|---|---:|---|
| [test_review_agent.py](../tests/unit/test_review_agent.py) | 94 | Review input/output validation, limits, model errors, rendering, metadata and factory |
| [test_test_agent.py](../tests/unit/test_test_agent.py) | 64 | Command validation, no-LLM invariant, sandbox failures, redaction, truncation and reports |
| [test_fix_agent.py](../tests/unit/test_fix_agent.py) | 51 | Replacement semantics, stale reports, scope, secrets, errors, limits, context and factory |
| [test_code_agent_chain.py](../tests/integration/test_code_agent_chain.py) | 3 | Review-only, test-only and combined failure followed by Fix and successful recheck |
| **Added** | **212** | |
| **Current suite** | **920** | **404 subtests unchanged** |

No existing test file was edited in this task. Existing assertions were not
deleted or loosened. The final pytest run reported no skips, xfails or failures.
The existing 11 chain tests remain alongside the three new chain scenarios.

The chain tests compose real agent classes and factories, but their ModelGateway,
RepositoryPort and SandboxPort are fakes. A passing sandbox result is scripted,
not evidence that generated code was executed in a real isolated process.

## 4. Final gates

All Python commands used `.\.venv\Scripts\python.exe`.

| Gate | Exit | Result |
|---|---:|---|
| `-m pytest tests\ -x -q` | 0 | 920 passed, 404 subtests passed |
| `-m mypy src\ --strict` | 0 | No issues in 89 source files |
| `-m ruff check src\ tests\` | 0 | All checks passed |
| `-m bandit -r src\` | 0 | No findings; one pre-existing specifically disabled issue |
| `rg -n 'TODO\|FIXME' 'src\asf\agents\implement' -g '*.py'` | 1 | No matches; expected no-match exit |
| Phase 7 coverage run | 0 | 920 passed, 404 subtests; 98% selected-scope statement coverage |

No new noqa, type-ignore or nosec suppression was added. The existing YAML B506
suppression is unchanged. The historical secret-scanning issue is not resolved
or re-approved by these gates.

### Coverage

| Module/scope | Statement coverage |
|---|---:|
| Review agent, factory, prompts | 100% each |
| Test agent and factory | 100% each |
| Fix agent | 98% |
| Fix factory and prompts | 100% each |
| Existing Implement agent | 95% |
| Shared code-agent request validation | 96% |
| Shared code-generation helpers | 93% |
| Entire selected Phase 7 scope | 98% (1,317 statements, 30 missing) |

Coverage is statement coverage, not a feature-parity or security proof.

## 5. Raw gate output

### Pytest

```text
.............................................. [  5%]
.................................................................................... [ 14%]
..................................................................... [ 21%]
........................................................................ [ 29%]
........................................................................ [ 37%]
............................................ [ 42%]
........................................................................ [ 49%]
........................................................................ [ 57%]
............................................................................................. [ 67%]
........................................................................ [ 75%]
........................................................................ [ 83%]
........................................................................ [ 91%]
.............................................................. [ 98%]
..................                                             [100%]
920 passed, 404 subtests passed in 4.16s
EXIT_CODE=0
```

### Mypy

```text
Success: no issues found in 89 source files
EXIT_CODE=0
```

### Ruff

```text
All checks passed!
EXIT_CODE=0
```

### Bandit

```text
[main] INFO profile include tests: None
[main] INFO profile exclude tests: None
[main] INFO cli include tests: None
[main] INFO cli exclude tests: None
[main] INFO running on Python 3.13.5
Working... ---------------------------------------- 100% 0:00:01
Run started:2026-11-02 07:22:30.756088+00:00

Test results:
    No issues identified.

Code scanned:
    Total lines of code: 7164
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
EXIT_CODE=0
```

Bandit whitespace is normalized here; original terminal output and the complete
coverage output are retained in the session evidence files.

### TODO/FIXME

```text
EXIT_CODE=1
```

There was no matching output.

## 6. Files changed in this task

Pre-existing staged/unstaged changes outside this list were preserved.

| File | Change |
|---|---|
| README.md | Replace obsolete initial status with implemented-agent/live-integration boundary |
| docs/architecture/phase-7-code-agents.md | Record implementation locations and explicit agent-error routing |
| docs/PHASE_7_C3_C5_REPORT.md | This requested verification report |
| src/asf/agents/README.md | Document implemented agents, deterministic testing and expected errors |
| src/asf/agents/base.py | Add expected agent/port error mapping and preflight rejection support |
| src/asf/agents/_shared/code_agents.py | Shared request, artifact, task and CODE link validation |
| src/asf/agents/_shared/codegen.py | Extract generated-code validation and secret issue reporting |
| src/asf/agents/implement/agent.py | Delegate existing validation to shared functions; keep C2 contract |
| src/asf/agents/loading.py | Add Review/Fix packaged prompt loaders |
| src/asf/agents/review/__init__.py | Export ReviewAgent, prompts and builder |
| src/asf/agents/review/agent.py | Implement C3 review execution |
| src/asf/agents/review/prompts.py | Validate review content and render/build messages |
| src/asf/agents/review/factory.py | Build configured ReviewAgent |
| src/asf/agents/review/prompts/system.md | Provider-neutral review prompt |
| src/asf/agents/review/README.md | Describe public API and validation contract |
| src/asf/agents/test/__init__.py | Export deterministic TestAgent and builder |
| src/asf/agents/test/agent.py | Validate/run sandbox commands and sanitize results |
| src/asf/agents/test/factory.py | Build TestAgent with injected sandbox |
| src/asf/agents/test/prompts.py | Document deterministic, no-LLM behavior |
| src/asf/agents/test/README.md | Describe command source, reports and error behavior |
| src/asf/agents/fix/__init__.py | Export FixAgent and builder |
| src/asf/agents/fix/agent.py | Implement C5 replacement and revision validation |
| src/asf/agents/fix/prompts.py | Build complete-replacement model context |
| src/asf/agents/fix/factory.py | Build configured FixAgent |
| src/asf/agents/fix/prompts/system.md | Provider-neutral replacement instructions |
| src/asf/agents/fix/README.md | Describe input links and replacement semantics |
| templates/review/CODE_REVIEW.md | Align verdict name with APPROVE / CHANGES_REQUESTED |
| tests/unit/test_review_agent.py | Add 94 review cases |
| tests/unit/test_test_agent.py | Add 64 deterministic-runner cases |
| tests/unit/test_fix_agent.py | Add 51 fix cases |
| tests/integration/test_code_agent_chain.py | Add three full fake-driven rework scenarios |

## 7. Explicitly retained C2 differences

The user chose to keep the already-approved C2 behavior and its existing
assertions rather than alter that contract in this task:

1. ImplementAgent oversized-base behavior remains INTEGRATION_UNAVAILABLE,
   whereas D10 describes REJECTED/VALIDATION_FAILED.
2. Its existing repository-failure tests preserve INTEGRATION_UNAVAILABLE,
   whereas D11 describes REPOSITORY_ERROR.

The new FixAgent uses the documented explicit error paths, but this report does
not claim all legacy ImplementAgent behavior has been realigned with D1-D16.

## 8. Manual reviewer commands

From the repository root in PowerShell:

```powershell
# New C3-C5 and rework-chain tests: 212 cases.
.\.venv\Scripts\python.exe -m pytest tests\unit\test_review_agent.py tests\unit\test_test_agent.py tests\unit\test_fix_agent.py tests\integration\test_code_agent_chain.py -v

# Existing chain plus new rework scenarios: 14 cases.
.\.venv\Scripts\python.exe -m pytest tests\integration\ -v

# Whole backend.
.\.venv\Scripts\python.exe -m pytest tests\ -x -q
.\.venv\Scripts\python.exe -m mypy src\ --strict
.\.venv\Scripts\python.exe -m ruff check src\ tests\
.\.venv\Scripts\python.exe -m bandit -r src\

# Coverage, including legacy shared/tools modules.
.\.venv\Scripts\python.exe -m pytest tests\ -q --cov=asf.agents.implement --cov=asf.agents.review --cov=asf.agents.test --cov=asf.agents.fix --cov=asf.tools --cov=asf.agents._shared --cov-report=term-missing
```

These commands use fakes and do not call the real provider.

## 9. Remaining boundaries

- Phase 6 must dispatch agents and implement the REWORK loop; tests do that
  composition explicitly, not via a production orchestrator.
- No real repository adapter or process-isolating sandbox was built.
- No real model-backed chain or generated-code execution was performed.
- No GitLab MR, CI pipeline, Teams notification or real backend API was added.
- Artifacts are returned to the caller; durable persistence is a separate concern.
- Secret redaction is pattern-based and is not a guarantee against all secret
  formats, prompt injection or sandbox escape.
- Historical secret-scanning/push-protection findings remain a separate reviewer
  decision; this task did not touch history or agent refs.
- Worktree literal scan returned zero matches under the previously supplied
  regex, reporting locations only. This is not a substitute for a full secret scan.

Conclusion: C3-C5 agent implementation and fake-driven verification are complete
within the agreed scope. Live-chain validation and operational/security approval
remain separate.
