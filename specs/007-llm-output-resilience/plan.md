# Implementation Plan: LLM Output Resilience

**Spec**: `specs/007-llm-output-resilience/spec.md`

**Status**: Draft, awaiting owner review. Documentation only in
this step; no product code.

## Findings the plan rests on (from grep on `origin/master` @ `a2eed49`)

(a) **agent-task does not pass through `_shared/repair.py`.** It
raises "Model response is not valid task JSON" at
`src/asf/agents/task/agent.py:570` with details
`{"parseError": str(error)}` only. The repair loop
(`src/asf/agents/_shared/repair.py:142`) is typed to `ChangeSet`
output and serves implement/fix only.

(b) **Step-level retry does not feed the parse error back.**
`src/asf/orchestrator/engine.py:838` `_retry` checks the step's
retry policy and schedules a re-dispatch after backoff. The
re-dispatched agent builds the same request; only the fix agent
receives `previousFixError`. That is why the two artifact-review
requests ~75 s apart in the evidence reproduced the same
`json_invalid` failure: same prompt, same model behaviour.

(c) **Raw model replies are not stored anywhere.** `response.content`
is consumed in-memory by each parser. What exists today: the spec
agent logs a redacted preview on rejection
(`src/asf/agents/spec/agent.py:234`); artifact-review
(`src/asf/agents/artifact_review/agent.py:259`) and review
(`src/asf/agents/review/agent.py:240`) log schema problems plus
`replyChars`/`finishReason`; executions persist outputs and errors,
not raw replies; Live Map events are metadata-only. There is no
DEBUG log, DB table, or tools log holding the raw reply — hence R1
must capture the excerpt at rejection time, in details.

(d) **Why agent-task ran exactly once while artifact-review ran
twice.** The task step has no `retryPolicy`
(`workflow-definitions/software-development.yaml:34`; only `ci`
at line 100 and `merge` at line 116 carry one), so
`engine._retry` (`src/asf/orchestrator/engine.py:838-860`) returns
False on `policy is None` even though `LLM_INVALID_RESPONSE` is
retryable (`src/asf/agents/_shared/model_errors.py` builds it with
`retryable=True`). Artifact-review's second request came from the
AI-review gate, which re-dispatches a failed reviewer up to
`MAX_REVIEW_ATTEMPTS` with a scheduled delay
(`src/asf/orchestrator/ai_review_apply.py:170-179`) — a different
mechanism from step retry. Enabling a step `retryPolicy` for the
task step is therefore a separate option from R2's
retry-with-feedback, and is recorded as its own decision in
Phase B, not bundled into it.

## Approach

1. **Evidence helper in `_shared`** (R1): one function taking the
   `ModelResponse`, an optional failure offset, and the repair
   count; returns the details dict (`replyChars`, `finishReason`,
   `repairsAttempted`, redacted `excerpt`) and emits the matching
   warning line. Window sizes are named constants. Offset sources:
   pydantic/JSON errors expose line/column (task column 504 in the
   evidence); template failures have no offset and use the bounded
   preview.
2. **Shared retry driver** (R2): generalize the `repair.py` loop
   shape to a parse callable returning the agent's validated value,
   reusing the `ebe9af5` spec retry note. Policy: at most 1 retry;
   `finishReason=length` (truncation) and secret findings never
   retry; usage summed; final failure is `invalid_response` with R1
   details. Implement/fix canonical messages and details stay
   byte-identical.
3. **Preprocessing** (R3): one shared helper replacing per-agent
   fence handling — strip code fence, extract a single unambiguous
   top-level `{...}`; no guessed repairs. Clean replies parse
   byte-identically to today.
4. **Wiring**: task (`task/agent.py:570`), artifact-review
   (`artifact_review/agent.py:259`), review
   (`review/agent.py:240`), plan section checks, and the spec
   agent's `_obtain_valid_reply` all route through the shared
   driver + evidence helper.
5. **JSON mode** (R4): record provider support as an opt-in
   settings option, default off; no enabling code in this feature.

## Verification

Per acceptance task in `tasks.md`, each with its test. Gates per
constitution III: `ruff check src tests harness`,
`ruff format --check src tests harness`, `mypy src`,
`bandit -c .bandit -r src -q`, `pytest -q`,
`python scripts/check_code_structure.py --baseline
.code-structure-baseline.json`, `gitleaks git --redact .`. Ratchet
baseline may only shrink.

## Risks

- One extra model call on failure paths: bounded at 1, usage
  summed and visible.
- Excerpt leakage: mitigated by `redact_text`, the ~80-char window,
  and a secret attack-case test.
- H1 may be wrong; R1 evidence settles it on the next failure
  without committing to fence-stripping as the cure.
