# Phase 7 – Code Agents Design

Reference document for ImplementAgent, ReviewAgent, TestAgent, FixAgent. Decisions only; no discussion.

---

## Corrected Decisions (D1–D16 with E1–E15 applied)

### D1 – Workflow YAML (commit C0)
Updated `workflows/software-development.yaml`:
- `implement` consumes `[SPEC, PLAN, TASK]`
- `review` consumes `[SPEC, PLAN, TASK, CODE]`
- `test` consumes `[TASK, CODE]`
- `ci` and `merge` unchanged (Phase 6/8).

### D2 – Naming
The T\<n> identifier is **`taskItemId`** everywhere:
- `AgentRequest.input.taskItemId` (required, `^T[1-9][0-9]*$`)
- `Artifact.metadata.taskItemId` on CODE, CODE_REVIEW, TEST_REPORT
- `AgentRequest.artifacts[*].metadata.taskItemId`
Never `taskId` (workflow work-item ID in `AgentRequest.taskId`).

### D3 – ImplementAgent (first generation only)
**Inputs** (validated in `_check`):
- Exactly 1 SPEC, 1 PLAN, 1 TASK
- **No CODE artifacts** (dependsOn tasks visible via RepositoryPort at `ref`)
- `input.ref` (opaque string, required) – base ref for repository reads
- No feedback, no previous CODE → **no revision mode**
- Reject any artifact type not in `{SPEC, PLAN, TASK}`

**Output**: single CODE artifact (see D12). Metadata:
`specArtifactId`, `specVersion`, `planArtifactId`, `planVersion`, `taskItemId`, `taskArtifactId`, `taskVersion`, `baseRef` (from `input.ref`).

### D4 – FixAgent
**Inputs**:
- SPEC, PLAN, TASK
- Exactly 1 CODE to fix (`metadata.taskItemId == input.taskItemId`)
- ≥1 of CODE_REVIEW / TEST_REPORT with `metadata.codeArtifactId == that CODE.id` AND `metadata.codeVersion == that CODE.version` (stale rejected)
- `input.ref` (required) – same baseRef as the CODE being fixed
- No feedback field

**Output**: COMPLETE replacement ChangeSet at same `baseRef` (not a diff), with:
- `revisionOf: <old CODE id>`
- `fixedReviewIds: [CODE_REVIEW.id, ...]`
- `fixedTestReportIds: [TEST_REPORT.id, ...]`

**Shared core**: plain functions in `src/asf/agents/_shared/codegen.py`:
```python
def build_implement_context(...) -> CodeGenContext
def build_fix_context(...) -> CodeGenContext
def generate_changeset(ctx: CodeGenContext, runtime) -> ChangeSet
```
ImplementAgent and FixAgent import and call these; **no inheritance**.

**State machine**: no changes in this branch; REWORK loop noted for Phase 6.

### D5 – Ports (`src/asf/tools/ports.py`)
```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol, Sequence
from pathlib import Path

@dataclass(frozen=True)
class CommandSpec:
    argv: tuple[str, ...]
    timeout_seconds: int = 120
    output_limit_bytes: int = 64_000

@dataclass(frozen=True)
class ChangeSet:
    changes: tuple[FileChange, ...]

@dataclass(frozen=True)
class FileChange:
    path: str
    operation: Literal["create", "modify", "delete"]
    content: str | None = None

@dataclass(frozen=True)
class CommandResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int

@dataclass(frozen=True)
class SandboxResult:
    commands: tuple[CommandResult, ...]

class RepositoryPort(Protocol):
    def list_tree(self, ref: str, prefix: str = "") -> tuple[str, ...]: ...
    def read_file(self, path: str, ref: str, max_bytes: int = 256_000) -> str: ...

class SandboxPort(Protocol):
    def run(self, commands: Sequence[CommandSpec], changes: ChangeSet, ref: str) -> SandboxResult: ...
```

**ChangeSet / FileChange** are Pydantic models in `src/asf/tools/changeset.py` (used by ports and agents). `tools/` does not import from `agents/`.

**Fakes** in `src/asf/tools/fake.py` (mirror `src/asf/models/fake.py`):
- `ScriptedSandbox` – pre-recorded `SandboxResult` per command signature
- `InMemorySandbox` – copies file tree at `ref` to `dict[str, str]`, applies `ChangeSet` (fails on modify/delete of missing path, rejects NUL/oversize/encoding), runs commands via argv→result table

`SandboxResult` returns **per-command results only**; no workspace snapshot.

### D6 – TestAgent
- **Commands**: ONLY from `context.project.testCommands` (list of argv lists). `verificationHint` is context only, never executed.
- **No LLM call in Phase 7** – deterministic runner only.
- **Result**: `status = SUCCESS` always unless infra failure; `verdict = PASS | FAIL` computed from exit codes (0 = pass, non-zero = FAIL including pytest exit 5).
- **Infra failures**: `FAILED` + `SANDBOX_ERROR` (runner exception) or `COMMAND_TIMEOUT` (any command exceeds timeout).
- **Output sanitization**: stdout/stderr truncated to `output_limit_bytes`, secret-redacted (shared detector), treated as untrusted data.
- **Validation** (in `_check`, one parse function): max 20 commands; each argv non-empty; each element non-empty, no NUL, max length; argv[0] bare executable name or relative path without ".."; timeout/output limits from `CommandSpec` defaults. No metacharacter filtering.

### D7 – ReviewAgent validation rules (enforced AFTER LLM call, on parsed reply)
- `verdict = APPROVE` **invalid** if any finding has `severity == "ERROR"` → `FAILED / LLM_INVALID_RESPONSE`
- Every `finding.path` must appear in CODE `ChangeSet.changes[*].path` → else `FAILED / LLM_INVALID_RESPONSE`
- `finding.line` optional; when present `>= 1`
- `MAX_FINDINGS = 100` hard constant; more → `FAILED / LLM_INVALID_RESPONSE`
- Whitespace-only strings rejected on all string fields
- **No import of state-machine triggers**; orchestrator maps `verdict` → trigger.

**Shared validation**: ReviewAgent and TestAgent both validate incoming CODE with the **same** `ChangeSet` Pydantic model.

### D8 – Secret detection
`configuration/secrets.py` only has `SecretRef` (reference pattern), **no arbitrary-text scanner**.

Define detector in `src/asf/agents/_shared/security.py`:
```python
SECRET_PATTERNS = [
    (re.compile(r"-----BEGIN (RSA|EC|OPENSSH) PRIVATE KEY-----"), "private_key"),
    (re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"][^\s'\"]{8,}['\"]"), "assignment"),
    (re.compile(r"(?i)(aws_access_key_id|aws_secret_access_key|github_token|gitlab_token)\s*[:=]\s*\S+"), "well_known"),
]
def scan(text: str) -> list[tuple[str, str]]: ...
```
On hit → `FAILED / LLM_INVALID_RESPONSE` with `details: {"paths": [...], "pattern": "..."}`; **never echo the secret**. Unit tests for hits and non-hits (long identifiers, hashes in tests, UUIDs).

### D9 – Scope & limits (enforced in code)
- **Allowed paths** = `TASK.expectedFiles` for that `taskItemId`
- Any `FileChange.path` not in allowed → `LLM_INVALID_RESPONSE` with `details.outOfScopePaths`
- **Denied paths** (always rejected even if listed): `.git/`, `.env*`, `*.pem`, `*.key`, `.github/`, `.gitlab-ci.yml`, `Jenkinsfile`, `package-lock.json`, `poetry.lock`, `Cargo.lock`, `pnpm-lock.yaml`
- `*.pem`, `*.key`, `.env*` rejected **even if** in `expectedFiles`
- **Limits** (constants in `_shared/limits.py`):
  - `MAX_CHANGES = 50`
  - `MAX_CHARS_PER_FILE = 200_000`
  - `MAX_TOTAL_CHARS = 500_000`
  - No NUL, UTF-8 only

### D10 – Context assembly for `modify` (before LLM call)
```python
for path in expected_files:
    if port.list_tree(ref).contains(path):
        try:
            content = port.read_file(path, ref, max_bytes=MAX_CHARS_PER_FILE)
            ctx.existing_files[path] = content
        except FileTooLarge:
            # too large → REJECTED / VALIDATION_FAILED (input problem)
            raise ValidationError(...)
    else:
        ctx.missing.add(path)
```
- `missing` on `modify`/`delete` in LLM reply → `LLM_INVALID_RESPONSE`
- `too_large` detected **before** LLM call → `REJECTED / VALIDATION_FAILED`
- Port failure → `FAILED / REPOSITORY_ERROR` (retryable)

### D11 – Failure-mode alignment (match PlanAgent/TaskAgent actuals)

| Situation | status | code | category | retryable |
|-----------|--------|------|----------|-----------|
| Validation failed (`_check`) | REJECTED | VALIDATION_FAILED | VALIDATION | false |
| LLM timeout | FAILED | LLM_TIMEOUT | LLM | true |
| LLM rate limited | FAILED | LLM_RATE_LIMITED | LLM | true |
| LLM empty / parse error / validation error | FAILED | LLM_INVALID_RESPONSE | LLM | false |
| Unexpected exception | FAILED | AGENT_EXECUTION_FAILED | AGENT | true |
| Repository port read failure | FAILED | REPOSITORY_ERROR | INTEGRATION | true |
| Sandbox exception | FAILED | SANDBOX_ERROR | INTEGRATION | true |
| Command timeout | FAILED | COMMAND_TIMEOUT | INTEGRATION | true |

New codes added to:
- `src/asf/models/errors.py` → `ALLOWED_GATEWAY_ERROR_CODES`
- `contracts/errors.md` → catalog table

### D12 – Contracts (Pydantic content models, camelCase aliases)
```python
# src/asf/tools/changeset.py
class FileChange(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)
    path: str = Field(..., min_length=1, alias="path")
    operation: Literal["create", "modify", "delete"] = Field(..., alias="operation")
    content: str | None = Field(default=None, alias="content")

class ChangeSet(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)
    changes: list[FileChange] = Field(..., alias="changes", min_length=1, max_length=50)

# src/asf/agents/_shared/contracts.py
class Finding(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)
    severity: Literal["ERROR", "WARNING", "INFO"] = Field(..., alias="severity")
    path: str = Field(..., min_length=1, alias="path")
    line: int | None = Field(default=None, ge=1, alias="line")
    description: str = Field(..., min_length=1, alias="description")
    suggestion: str | None = Field(default=None, alias="suggestion")

class ReviewContent(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)
    findings: list[Finding] = Field(..., alias="findings")
    verdict: Literal["APPROVE", "CHANGES_REQUESTED"] = Field(..., alias="verdict")

class ReportContent(BaseModel):  # not TestReportContent (pytest collects Test*)
    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)
    commands: list[CommandResult] = Field(..., alias="commands")
    verdict: Literal["PASS", "FAIL"] = Field(..., alias="verdict")
    summary: str = Field(..., alias="summary")
```
**Contract validator test** (`tests/unit/contract_models.py` uses `validator_for` helper):
```python
def test_every_produced_artifact_validates_against_schema():
    for artifact in produced_artifacts:
        jsonschema.validate(artifact.to_contract(), load_schema("contracts.schema.json"))
```

### D13 – Shared code: `src/asf/agents/_shared/`
First extraction (C1) – only what new agents need:
```
_shared/
  __init__.py
  change_set.py          # re-exports from tools.changeset + validators
  paths.py               # validate_relative_path (expectedFiles rules)
  validation.py          # reject_whitespace_only, validate_no_duplicates, validate_list_no_whitespace
  parsing.py             # strip_code_fence
  traceability.py        # build_metadata(spec, plan, task, code?, review?, test?)
  limits.py              # MAX_* constants, check_size_limits
  security.py            # scan_secrets (D8)
  codegen.py             # build_implement_context, build_fix_context, generate_changeset (D4)
  contracts.py           # Finding, ReviewContent, ReportContent, CommandResult
```
**Duplicated in PlanAgent/TaskAgent (left untouched, later refactor)**:
- artifact selection/validation helpers
- version regex `^[1-9][0-9]*$`
- fence stripping
- whitespace/duplicate validators
- traceability metadata building
- size-limit checks
- ModelGatewayError wrapping (BaseAgent already does this)

### D14 – Skills
System prompt receives exactly one line:
```
Enabled skills: skill1, skill2, skill3
```
No skill-specific content blocks.

### D15 – Quality gates (exact commands)
```bash
ruff check .
mypy --config-file pyproject.toml src/
pytest -x -q
pytest --cov=src/asf/agents/implement --cov=src/asf/agents/review --cov=src/asf/agents/test --cov=src/asf/agents/fix --cov=src/asf/tools --cov=src/asf/agents/_shared --cov-report=term-missing
```
**pyproject.toml mypy config**:
```toml
[tool.mypy]
python_version = "3.12"
ignore_missing_imports = true
strict = false
```
**mypy on whole src tree (current master)** – pre-existing errors:
- `src/asf/configuration/yamlio.py` – missing yaml stubs (ignored by `ignore_missing_imports`)
- `src/asf/approval/service.py` – Literal type mismatch (pre-existing)
These are unrelated to our changes.

### D16 – Commit plan
| Commit | Scope |
|--------|-------|
| C0 | `workflows/software-development.yaml` + loader/workflow tests (updated consumes/produces) |
| C1 | `src/asf/tools/ports.py`, `src/asf/tools/changeset.py`, `src/asf/tools/fake.py`, `_shared/` modules + unit tests |
| C2 | ImplementAgent (`agent.py`, `prompts.py`, templates, `loading.py` loaders) + tests |
| C3 | ReviewAgent (`agent.py`, `prompts.py`, templates, `loading.py`) + tests |
| C4 | TestAgent (`agent.py`, `prompts.py`, templates, `loading.py`) + tests |
| C5 | FixAgent (`agent.py`, `prompts.py`, templates, `loading.py`) + tests |
| Each | Extend fake-driven chain test in `tests/integration/test_chain.py` |

---

## JSON Shape of Artifact Content

### CODE
```json
{
  "format": "json",
  "changeSet": {
    "changes": [
      {"path": "src/foo.py", "operation": "create", "content": "..."},
      {"path": "src/bar.py", "operation": "modify", "content": "..."},
      {"path": "old.py", "operation": "delete"}
    ]
  },
  "text": "# CODE: Implementation\n...\n## File: src/foo.py\n```python\n...\n```"
}
```

### CODE_REVIEW
```json
{
  "format": "json",
  "review": {
    "findings": [
      {"severity": "ERROR", "path": "src/foo.py", "line": 42, "description": "...", "suggestion": "..."}
    ],
    "verdict": "CHANGES_REQUESTED"
  },
  "text": "# CODE_REVIEW\n...\n## Finding: src/foo.py:42 [ERROR]\n..."
}
```

### TEST_REPORT
```json
{
  "format": "json",
  "report": {
    "commands": [
      {"argv": ["pytest", "tests/"], "exitCode": 0, "stdout": "...", "stderr": "", "durationMs": 123}
    ],
    "verdict": "PASS",
    "summary": "All tests passed"
  },
  "text": "# TEST_REPORT\n...\n## Command: pytest tests/\nExit code: 0\n..."
}
```

---

## Metadata Keys per Artifact

| Artifact | Keys (injected in code, never by LLM) |
|----------|--------------------------------------|
| SPEC | — |
| PLAN | `specArtifactId`, `specVersion`, `revisionOf?` |
| TASK | `specArtifactId`, `specVersion`, `planArtifactId`, `planVersion`, `revisionOf?` |
| CODE | `specArtifactId`, `specVersion`, `planArtifactId`, `planVersion`, `taskItemId`, `taskArtifactId`, `taskVersion`, `baseRef`, `revisionOf?` |
| CODE_REVIEW | `specArtifactId`, `specVersion`, `planArtifactId`, `planVersion`, `taskItemId`, `codeArtifactId`, `codeVersion` |
| TEST_REPORT | `specArtifactId`, `specVersion`, `planArtifactId`, `planVersion`, `taskItemId`, `codeArtifactId`, `codeVersion` |

---

## Validation Rules per Agent

### ImplementAgent `_check`
1. `agentId` matches
2. `input.taskItemId` present, matches regex
3. `input.ref` present, non-empty string
4. `input` keys ⊆ `{taskItemId, ref, language}`
5. Exactly 1 SPEC, 1 PLAN, 1 TASK
6. SPEC/PLAN/TASK content.text non-empty, versions match regex
7. TASK parses, contains `taskItemId`
8. TASK traceability matches SPEC/PLAN
9. No TASK artifact already (no revision mode)
10. No CODE artifacts present
11. No unknown artifact types
12. `metadata.attempt` valid if present
13. SPEC+PLAN+TASK content size ≤ limit

### ImplementAgent `_run` validations (after LLM)
- ChangeSet validates (Pydantic)
- All paths in `TASK.expectedFiles`
- No denied paths (D9)
- Size limits (D9)
- `modify`/`delete` targets exist at `ref` (RepositoryPort)
- No secrets in generated content (D8)
- Raw reply size ≤ `MAX_CODE_REPLY_CHARS`
- Rendered text size ≤ `MAX_CODE_TEXT_CHARS`

### ReviewAgent `_check`
1. `agentId` matches
2. `input.taskItemId` present
3. Exactly 1 SPEC, 1 PLAN, 1 TASK, 1 CODE
4. CODE `metadata.taskItemId == input.taskItemId`
5. All content.text non-empty, versions valid
6. TASK contains `taskItemId`
7. No unknown artifact types
8. `metadata.attempt` valid

### ReviewAgent `_run` validations (after LLM, D7)
- ReviewContent validates (Pydantic)
- `verdict == APPROVE` → no `ERROR` findings
- All `finding.path` in CODE `ChangeSet.changes[*].path`
- `finding.line` ≥ 1 when present
- `len(findings) ≤ MAX_FINDINGS`
- No whitespace-only strings
- Raw reply size ≤ limit
- Rendered size ≤ limit

### TestAgent `_check`
1. `agentId` matches
2. `input.taskItemId` present
3. Exactly 1 TASK, 1 CODE
4. CODE `metadata.taskItemId == input.taskItemId`
5. `context.project.testCommands` present, valid (parse function)
6. No unknown artifact types
7. `metadata.attempt` valid

### TestAgent `_run`
- Run each command via `SandboxPort`
- Sanitize outputs
- `verdict = PASS` iff all `exit_code == 0`
- Infra failure → `FAILED` + `SANDBOX_ERROR`/`COMMAND_TIMEOUT`
- Build ReportContent, render text
- Size limits

### FixAgent `_check`
1. `agentId` matches
2. `input.taskItemId` present
3. `input.ref` present
4. Exactly 1 SPEC, 1 PLAN, 1 TASK, 1 CODE
5. ≥1 CODE_REVIEW / TEST_REPORT
6. CODE `metadata.taskItemId == input.taskItemId`
7. Each review/report: `metadata.codeArtifactId == CODE.id` AND `metadata.codeVersion == CODE.version`
8. `input.ref == CODE.metadata.baseRef`
9. No unknown artifact types

### FixAgent `_run` validations
- Same as ImplementAgent + replacement ChangeSet at same `baseRef`
- `revisionOf`, `fixedReviewIds`, `fixedTestReportIds` in metadata

---

## Phase 6 / Phase 8 Notes

### Phase 6 (Orchestrator)
- REWORK loop: after `review` (CODE_REVIEW) or `test` (TEST_REPORT) produces `CHANGES_REQUESTED`/`FAIL`, orchestrator triggers `REVISE` on a `REWORK` stage that invokes FixAgent.
- Applying changes between tasks: when task T2 depends on T1, orchestrator applies T1's CODE to the workspace at `ref` before invoking ImplementAgent for T2. This is orchestrator responsibility, not agent.
- `ci` step: runs pipeline on the merged change set (Phase 8).
- `merge` step: awaits approvals on CODE_REVIEW and TEST_REPORT (Phase 6/8).

### Phase 8 (Real implementations)
- `RepositoryPort` → Git-backed (list_tree/read_file at commit/branch/tag)
- `SandboxPort` → real sandbox (container/VM, applies ChangeSet, runs commands, returns results)
- Secret scanning integrated with vault/secret manager
- CI integration for `ci` step
- Merge automation for `merge` step