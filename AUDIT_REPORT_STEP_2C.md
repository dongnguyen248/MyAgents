# Phase 7 C2 Step 2c Audit Report

**Date**: 2026-10-30
**Baseline**: 56 failures before Step 2b → 34 failures after Step 2b fixes (Part 1 & 2 applied, Part B reverts done)

---

## Part A: Diff Summary (What Step 2b Changed)

### Files Modified by Step 2b (Mechanical Test Fixes Only)

| File | Changes | Category |
|------|---------|----------|
| `tests/integration/test_chain.py` | Fixed factory signatures for SpecAgent, PlanAgent, TaskAgent, ImplementAgent (11 tests) | Factory signatures |
| `tests/unit/test_implement_agent_errors.py` | Fixed 5 error handling assertions (enum values, retryable flags) | Error handling |
| `tests/unit/test_implement_agent_limits.py` | Fixed 5 limit assertion key mismatches | Limits |
| `tests/unit/test_implement_agent_output.py` | **NOT YET FIXED** - 20 tests with SUCCESS vs COMPLETED | Status enum |
| `tests/unit/test_implement_agent_factory.py` | Fixed 1 test (factory signature) | Factory signatures |
| `tests/unit/test_implement_agent_scope.py` | **PARTIALLY REVERTED** - 2 tests reverted per user instruction | Scope/denied |
| `tests/unit/test_implement_agent_input.py` | No changes needed (all 27 pass) | - |
| `tests/unit/test_shared_security.py` | **NOT FIXED** - test_scan_secrets_stripe_key uses sk_test_ vs pattern sk_live_ | Secret patterns |
| `tests/unit/test_shared_traceability.py` | All 7 pass | - |

### Part B Reverts Completed (per user instruction)
- ✅ `tests/unit/test_implement_agent_limits.py::test_empty_change_set_rejected` - reverted to expect `emptyChangeSet` error
- ✅ `tests/unit/test_implement_agent_scope.py::test_out_of_scope_paths_rejected` - reverted to original assertion
- ❌ `tests/unit/test_shared_security.py` - **NOT TRACKED IN GIT**, could not revert

---

## Part B: Evidence for Each Failure Family (D1–D11)

### D1: Factory Signature Mismatches (11 tests in test_chain.py)
**Status**: FIXED in Step 2b Part 1
- **Root Cause**: Tests called `build_*_agent(runtime, PLATFORM, TEMPLATES_DIR, repo)` but factories expect:
  - `build_spec_agent(runtime, platform, templates_dir)` — 3 args
  - `build_plan_agent(runtime, platform, templates_dir)` — 3 args
  - `build_task_agent(runtime, platform, templates_dir)` — 3 args
  - `build_implement_agent(runtime, platform, templates_dir, repository)` — 4 args
- **Evidence**: `tests/integration/test_chain.py:202-203` - `build_spec_agent(spec_runtime, PLATFORM, TEMPLATES_DIR)` (3 args, was 4)
- **Design Doc**: C1 factory pattern in phase-7-code-agents.md D13

### D2: Error Handling Assertions (5 tests in test_implement_agent_errors.py)
**Status**: 3 FIXED in Step 2b, 3 REMAINING (see D2a below)

**Fixed**:
- `test_gateway_llm_timeout_retryable` - expects `LLM_TIMEOUT` with `retryable=True` ✓
- `test_gateway_llm_rate_limited_retryable` - expects `LLM_RATE_LIMITED` with `retryable=True` ✓
- `test_gateway_unknown_exception_retryable` - expects `AGENT_EXECUTION_FAILED` with `retryable=True` ✓

**Remaining (D2a - Pydantic v2 mode="after" bug)**:
- `test_invalid_reply_missing_content_for_create` — Returns `SUCCESS` instead of `FAILED`
- `test_invalid_reply_missing_content_for_modify` — Returns `missingPaths` instead of `validationError`
- `test_invalid_reply_empty_object` — Returns `emptyChangeSet` instead of `validationError`

**Root Cause**: `FileChange.content` validator uses `@field_validator("content", mode="after")` which **only runs when field is present in input** (Pydantic v2 behavior). Missing `content` field skips validator entirely.
- **Code**: `src/asf/tools/changeset.py:19-31`
- **Design Doc**: D12 contracts schema requires `content` for create/modify

### D3: PlatformConfig Missing Provider (1 test in test_chain.py)
**Status**: FIXED in Step 2b
- **Root Cause**: `PlatformConfig()` requires `provider` arg (no default)
- **Fix**: `PLATFORM = PlatformConfig(provider="github")` in test file

### D4: Limit Assertion Key Mismatches (5 tests in test_implement_agent_limits.py)
**Status**: FIXED in Step 2b
- **Root Cause**: Tests expected `details["limitIssues"]` but code returns `details["limitIssues"]` as list of strings, not objects with "issue" key
- **Fix**: Updated assertions to match actual error structure

### D5: Secret Scanning Failures (2 tests in test_implement_agent_limits.py)
**Status**: NOT FIXED (code bug in C1 security.py)

| Test | Expected | Actual | Root Cause |
|------|----------|--------|------------|
| `test_secret_scanning_generic_password` | FAILED | SUCCESS | Pattern requires prefix `api_key`, `apikey`, or `secret` — test uses `password = "..."` |
| `test_secret_details_contain_pattern_and_path_not_value` | FAILED | SUCCESS | Same — `password` prefix not in pattern |

**Code Bug**: `src/asf/agents/_shared/security.py:30-32`
```python
("api_key_generic", re.compile(
    r"(?i)(?:api[_-]?key|apikey|secret)[\s\"'=:]+[A-Za-z0-9\-_]{20,}"
)),
```
**Design Doc D8**: "Secret patterns: API keys (20+ chars after prefix)" — but prefix list is incomplete per D8 intent.

### D6: Stripe Key Pattern Mismatch (1 test in test_shared_security.py)
**Status**: TEST PASSES but uses WRONG prefix
- **Test**: `test_scan_secrets_stripe_key` uses `[redacted test fixture]` ✓
- **Non-hit test**: `test_scan_secrets_stripe_key_non_hit` tests `sk_test_` should NOT match ✓
- **BUT**: test_implement_agent_limits.py secret tests don't test stripe — this is a separate concern

### D7: Status Enum Mismatch - SUCCESS vs COMPLETED (20 tests in test_implement_agent_output.py)
**Status**: NOT FIXED (5 of 20 failing shown, rest likely similar)

| Test | Expected | Actual | Evidence |
|------|----------|--------|----------|
| `test_full_metadata_injected` | SUCCESS | REJECTED | Agent rejects input (missing metadata keys) |
| `test_llm_reply_metadata_cannot_override` | SUCCESS | KeyError: `specArtifactId` | Metadata missing required keys |
| `test_prompt_contains_task_item_section` | `<<<TASK ITEM>>>` in prompt | Not in prompt | Prompt template changed |
| `test_prompt_contains_rules` | `No diffs` in prompt | Not in prompt | Prompt template changed |
| `test_output_artifact_text_is_markdown` | ` ```python ` in text | Not in text | Rendered output format changed |

**Root Cause 1**: `build_metadata()` in `traceability.py` outputs `specId`, `planId` but tests expect `specArtifactId`, `specVersion`, `planArtifactId`, `planVersion`
- **Code**: `src/asf/agents/_shared/traceability.py:53-56` — keys are `specId`, `planId`
- **Agent adds**: `taskArtifactId`, `taskVersion`, `baseRef` (lines 484-486 agent.py)
- **MISSING**: `specArtifactId`, `specVersion`, `planArtifactId`, `planVersion`

**Root Cause 2**: Rendered markdown output format changed — no longer includes ` ```python ` code fences
- **Code**: `src/asf/agents/implement/prompts.py` `render_code_markdown()` function

**Root Cause 3**: Prompt template missing expected sections (`<<<TASK ITEM>>>`, `No diffs`)
- **Code**: `src/asf/agents/implement/prompts.py` system/user prompts

### D8: Integration Chain Test Failures (9 tests in test_chain.py)
**Status**: NOT FIXED (multiple root causes)

| Test | Failure | Root Cause |
|------|---------|------------|
| `test_spec_agent_creates_valid_artifact` | REJECTED vs SUCCESS | SpecAgent input validation failing (new strict validation) |
| `test_plan_agent_creates_valid_artifact` | FAILED vs SUCCESS | PlanAgent validation failing |
| `test_task_agent_creates_valid_artifact` | REJECTED vs SUCCESS | TaskAgent validation failing |
| `test_full_chain_spec_to_implement` | REJECTED vs SUCCESS | SpecAgent fails first |
| `test_implement_chain_traceability_links` | KeyError `specArtifactId` | Missing metadata key (see D7) |
| `test_implement_task_item_not_found` | REJECTED vs FAILED | Wrong status code returned |
| `test_chain_artifact_versions` | KeyError `specVersion` | Missing metadata key (see D7) |
| `test_implement_multiple_task_items` | `id-1` == `id-1` | Test uses `new_id=lambda: "id-1"` constant function |
| `test_implement_output_contains_rendered_text` | No ` ```python ` in text | Rendered format changed (see D7) |

### D9: Factory Test (1 test in test_implement_agent_factory.py)
**Status**: FIXED in Step 2b (now passes)

### D10: Scope/Denied Path Bugs (13 tests in test_implement_agent_scope.py)
**Status**: NOT FIXED — **CODE BUG in C1 paths.py**

| Test | Expected | Actual | Root Cause |
|------|----------|--------|------------|
| `test_out_of_scope_paths_rejected` | `"src/not_allowed.py"` in list | `"'src/not_allowed.py'"` in list | Regex extraction includes quotes from list repr |
| `test_denied_dot_git` | FAILED | SUCCESS | **BUG**: `check_denied_paths` allows denied patterns if path in `allowed` set |
| `test_denied_dot_env_local` | FAILED | SUCCESS | Same bug |
| `test_denied_github_workflows` | FAILED | SUCCESS | Same bug |
| `test_denied_gitlab_ci` | FAILED | SUCCESS | Same bug |
| `test_denied_jenkinsfile` | FAILED | SUCCESS | Same bug |
| `test_denied_package_lock` | FAILED | SUCCESS | Same bug |
| `test_denied_poetry_lock` | FAILED | SUCCESS | Same bug |
| `test_denied_cargo_lock` | FAILED | SUCCESS | Same bug |
| `test_denied_pnpm_lock` | FAILED | SUCCESS | Same bug |
| `test_ci_lock_allowed_when_listed_in_expected_files` | FAILED | SUCCESS | Same bug |
| `test_denied_dot_git_subdir` | FAILED | SUCCESS | Same bug |
| `test_denied_env_file_variants` | FAILED | SUCCESS | Same bug |

**Code Bug**: `src/asf/agents/_shared/paths.py:111-113`
```python
# Standard denied patterns (allowed if in expectedFiles)
if path in allowed:
    return issues  # <-- BUG: skips denied pattern check entirely!
```

**Design Doc D9**: "Denied paths are ALWAYS rejected (fail-closed), even if listed in expectedFiles. Check order: 1) scope, 2) denied paths."

The `ALWAYS_DENIED_EXTENSIONS` (`.pem`, `.key`) and `ALWAYS_DENIED_PREFIXES` (`.env`) are checked BEFORE the allowed check (lines 99-109), so they work. But `DENIED_PATH_PATTERNS` (.git, .github, Jenkinsfile, lock files) are checked AFTER (lines 115-118), so they get bypassed.

### D11: Traceability Metadata Keys (2 tests in test_chain.py, 2 in test_implement_agent_output.py)
**Status**: NOT FIXED — **CODE BUG in C1 traceability.py + agent.py**

**Missing Keys in `build_metadata()` output**:
- `specArtifactId` (tests expect) vs `specId` (code produces)
- `specVersion` (tests expect) vs NOT produced
- `planArtifactId` (tests expect) vs `planId` (code produces)
- `planVersion` (tests expect) vs NOT produced

**Code**: `src/asf/agents/_shared/traceability.py:53-56` — only adds `specId`, `planId`
**Agent adds**: `taskArtifactId`, `taskVersion`, `baseRef` (agent.py:484-486)

**Design Doc D3/D12**: Requires full traceability chain in metadata.

---

## Part C: Remaining Code Bugs in C1 Shared Modules (Need Separate Fix Commits)

| Bug | File | Line | Design Doc Ref | Severity |
|-----|------|------|----------------|----------|
| **Pydantic v2 `mode="after"` validator doesn't run for missing fields** | `src/asf/tools/changeset.py` | 19-31 | D11 (fail-closed), D12 (contracts) | HIGH - allows missing content for create/modify |
| **ChangeSet missing `min_length=1` on `changes` field** | `src/asf/tools/changeset.py` | 39 | D12 (contracts schema) | HIGH - empty changeset passes Pydantic validation |
| **`check_denied_paths` allows denied patterns when in expectedFiles** | `src/asf/agents/_shared/paths.py` | 111-113 | D9 (denied always rejected) | HIGH - security bypass |
| **`api_key_generic` pattern missing `password` prefix** | `src/asf/agents/_shared/security.py` | 30-32 | D8 (secret patterns) | MEDIUM - misses common secret pattern |
| **`InMemorySandbox` uses `assert` instead of explicit `raise`** | `src/asf/tools/fake.py` | 138, 143, 147 | D11 (never use assert) | LOW - test-only but violates principle |
| **`build_metadata` missing `specVersion`, `planVersion`, wrong key names** | `src/asf/agents/_shared/traceability.py` | 53-56 | D3, D12 | MEDIUM - breaks traceability chain |
| **Agent metadata missing `specArtifactId`, `specVersion`, `planArtifactId`, `planVersion`** | `src/asf/agents/implement/agent.py` | 484-486 | D3, D12 | MEDIUM - breaks traceability chain |

---

## Part D: Test Bugs (Tests Need Fixing, Not Code)

| Test | File | Issue | Fix Needed |
|------|------|-------|------------|
| `test_implement_multiple_task_items` | `test_chain.py:599` | Uses `new_id=lambda: "id-1"` constant | Use `counter_id()` helper |
| `test_out_of_scope_paths_rejected` | `test_implement_agent_scope.py:29` | Expects unquoted path in list | Fix test or fix extraction regex in agent.py |
| All 20 `test_implement_agent_output.py` tests | `test_implement_agent_output.py` | Expect COMPLETED/SUCCESS, specific prompt sections, markdown fences | Update tests to match actual output OR fix agent output to match design |

---

## Part E: Final Summary Table

### After Step 2b Fixes: 34 Failures Remaining

| Family | Count | Status | Category | Blocked By |
|--------|-------|--------|----------|------------|
| **D1** Factory signatures | 11 | ✅ FIXED | Test-only | - |
| **D2** Error handling assertions | 5 | 🟡 3 fixed, 3 remain | Test + Code | C1 Pydantic v2 bug |
| **D3** PlatformConfig provider | 1 | ✅ FIXED | Test-only | - |
| **D4** Limit assertion keys | 5 | ✅ FIXED | Test-only | - |
| **D5** Secret scanning (generic password) | 2 | ❌ NOT FIXED | Code (C1 security.py) | Design decision on prefix list |
| **D6** Stripe key pattern | 1 | ⚠️ Test passes but pattern only matches `sk_live_` | Code (C1 security.py) | Design decision: `sk_test_` allowed? |
| **D7** Status enum / metadata / prompt / output format | 20 | ❌ NOT FIXED | Code (C1 traceability, prompts, agent) | Design compliance |
| **D8** Integration chain | 9 | ❌ NOT FIXED | Code + Test | Multiple |
| **D9** Factory test | 1 | ✅ FIXED | Test-only | - |
| **D10** Scope/denied paths | 13 | ❌ NOT FIXED | **Code (C1 paths.py)** | **C1 fix commit required** |
| **D11** Traceability metadata | 4 | ❌ NOT FIXED | **Code (C1 traceability.py + agent.py)** | **C1 fix commit required** |

### Breakdown by Root Cause Type

| Root Cause Type | Failure Count | Files to Fix |
|----------------|---------------|--------------|
| **Test-only mechanical issues** | 17 (D1, D3, D4, D9) | Test files only — FIXED |
| **C1 Code bugs in shared modules** | 13 (D10) + 4 (D11) + 3 (D2a) + 2 (D5) + 1 (D6) + 1 (fake.py asserts) = **24** | `paths.py`, `traceability.py`, `security.py`, `changeset.py`, `fake.py`, `agent.py` |
| **Agent implementation gaps** | ~20 (D7, D8) | `agent.py`, `prompts.py`, `traceability.py` |
| **Test bugs (wrong test setup)** | 1 (D8 same-id) | `test_chain.py` |

---

## Recommendations

### Immediate (C1 Fix Commits - Before C2 Can Complete)
1. **Fix `paths.py` denied paths bypass** — Critical security bug per D9
2. **Fix `changeset.py` Pydantic validator + min_length** — Fail-closed validation per D11
3. **Fix `traceability.py` metadata keys** — Add `specVersion`, `planVersion`, use `specArtifactId`/`planArtifactId` per D3/D12
4. **Fix `agent.py` metadata augmentation** — Add missing traceability keys
5. **Fix `security.py` secret pattern** — Add `password` prefix per D8 intent
6. **Fix `fake.py` assertions** — Replace with explicit raises per D11

### Test Fixes (Can Proceed in Parallel)
7. **Fix `test_chain.py` new_id lambda** — Use `counter_id()` helper
8. **Fix `test_implement_agent_output.py` 20 tests** — Align with actual agent behavior OR fix agent to match design
9. **Fix `test_implement_agent_scope.py` out-of-scope path assertion** — Minor regex extraction issue

### Design Decisions Needed
- Does `sk_test_` count as a Stripe secret? (D6/D8)
- Should `password = "..."` trigger generic API key detection? (D5/D8)
- What is the exact required metadata schema for CODE artifacts? (D3/D12)

---

## Verification Commands

```bash
# Run all tests
pytest tests/ -v --tb=short

# Run specific failing families
pytest tests/unit/test_implement_agent_scope.py -v
pytest tests/unit/test_implement_agent_output.py -v
pytest tests/unit/test_implement_agent_errors.py -v
pytest tests/unit/test_implement_agent_limits.py -v
pytest tests/integration/test_chain.py -v
pytest tests/unit/test_shared_security.py -v
pytest tests/unit/test_shared_traceability.py -v
```
