# Feature Specification: LLM Output Resilience

**Feature Branch**: `spec/007-llm-output-resilience` (documentation only in this step)

**Created**: 2026-11-26

**Status**: Draft, awaiting owner review

**Input**: Agents returning JSON or template output (`agent-task`,
`agent-artifact-review`, `agent-spec`, `agent-plan`) fail with
`LLM_INVALID_RESPONSE`, and the log does not carry enough evidence to
diagnose why.

## Evidence (verified on Windows, `data/logs/asf.log`, run `9be008dc-4502-492f-b807-679bf1210421`, 2026-11-26)

- 13:36:50 and 13:38:05: `agent-artifact-review` reply rejected:
  `(root): json_invalid`, `replyChars=2540` and `3868`,
  `finishReason=stop` — so the replies were NOT truncated.
- The two requests are ~75 s apart with different request ids: a
  step-level retry already happened, and it reproduced the failure.
- 13:39:40: `agent-task` "Model response is not valid task JSON",
  pydantic `expected ',' or ']' at line 1 column 504`; error details
  carry only `parseError` with `input_value` truncated in the middle —
  no `replyChars`, `finishReason`, `repairsAttempted`, or excerpt.

## Current state (verified on `origin/master` @ `a2eed49`)

- `agent-task` raises at `src/asf/agents/task/agent.py:570`
  ("Model response is not valid task JSON") with details
  `{"parseError": str(error)}` only. No hit for
  `repairsAttempted`/`replyChars`/`finishReason` exists in the task
  agent.
- `src/asf/agents/artifact_review/agent.py:259` and
  `src/asf/agents/review/agent.py:240` log `replyChars`/`finishReason`
  in one warning line but do not put them into error details.
- `src/asf/agents/fix/agent.py:233-234` and `436-437` put
  `replyChars`/`finishReason` into details;
  `src/asf/agents/_shared/model_call.py:47,57` stamps `finishReason`
  on truncation/blocked errors; `src/asf/agents/_shared/repair.py:132`
  stamps `repairsAttempted` when the code-agent repair loop runs out.
- The repair loop (`src/asf/agents/_shared/repair.py:142`
  `_repair_request`) serves implement/fix only; task, spec, plan,
  and artifact-review do not pass through it.
- Commit `ebe9af5` (spec agent retries once on missing template
  sections, `src/asf/agents/spec/agent.py:234`) is already in
  `origin/master`. R2 reuses and generalizes it; it is not rewritten.
- Step-level retry (`src/asf/orchestrator/engine.py:838` `_retry`)
  only schedules a re-dispatch with backoff. The re-dispatched agent
  receives the same request; only the fix agent gets a
  `previousFixError` input. Parse errors are not fed back to
  task/spec/plan/artifact-review, which is why the step retry above
  reproduced the same failure.
- No raw model reply is persisted: `response.content` is consumed
  in-memory by the parsers; the spec agent logs a redacted preview
  (`src/asf/agents/spec/agent.py:234`), artifact-review/review log
  schema problems plus counts, and executions store outputs/errors,
  not raw replies. Diagnosis today depends on those log lines alone.

## Hypothesis H1 (unverified)

Some `json_invalid` replies may be valid JSON wrapped in a code
fence or surrounded by prose. This is NOT verified — the raw replies
were not stored. R1 is the instrument that verifies or refutes H1 on
the next failure.

For the task agent specifically, H1 does not explain the evidence:
`unwrap_code_fence` already runs before parsing
(`src/asf/agents/task/agent.py:463`), so the
`expected ',' or ']' at column 504` failure is not a fence problem.
The alternative hypothesis — an unescaped string or a missing comma
inside the JSON — is UNVERIFIED until R1 captures the excerpt.

Fence stripping status per agent (verified): `unwrap_code_fence`
runs in task (`task/agent.py:463`), plan (`plan/agent.py:188`),
spec (`spec/agent.py:261`), and implement
(`implement/agent.py:344`). Artifact-review and review already
strip fences through their own parser helper `strip_code_fence`
(`src/asf/agents/artifact_review/agent.py:254`,
`src/asf/agents/review/agent.py:235`). So no agent lacks fence
stripping; R3's remaining value is prose extraction around a
single JSON object, which none of them do today.

## Requirements

### R1. Centralized observability in `_shared`

Every `LLM_INVALID_RESPONSE` branch in agent-task,
agent-artifact-review, agent-review, agent-spec, and agent-plan puts
into error details, via one shared helper:

- `replyChars` — length of the raw model reply;
- `finishReason` — the provider finish reason;
- `repairsAttempted` — feedback retries used (0 when none);
- `excerpt` — the reply region around the failure offset, at most
  ~80 characters on each side when an offset is known, passed
  through `redact_text`; a bounded redacted preview when no offset
  is known.

Secrets must never reach logs or details; the excerpt is redacted
before it is stored anywhere.

### R2. One shared retry-with-feedback

- On a parse/template failure, retry at most once, sending the
  specific parse/validation error back to the model.
- One shared mechanism generalizing `repair.py` and `ebe9af5`; no
  per-agent retry loops.
- Never retry when `finishReason=length`: that is truncation and
  needs a different remedy (token budget / smaller task), matching
  the existing `LLM_OUTPUT_TRUNCATED` policy.
- Secret findings are never retried.
- Usage of all calls is summed; after the budget, the final error
  is the standard `invalid_response` with R1 details.

### R3. Light preprocessing before parse

- Fence stripping already exists everywhere (see H1 status above)
  and is not re-implemented.
- Extract a single unambiguous top-level `{...}` block when prose
  surrounds it. This applies to the JSON-parsing agents that do
  not extract today: task, artifact-review, and review.
- Never repair JSON by guessing (no inserted commas, closing
  brackets, or quote fixes). Still-invalid output goes to R2, then
  fails with R1 evidence.
- R3 is Phase B: it starts only after Phase A log evidence shows
  prose-wrapped replies actually occur.

### R4. Provider JSON mode as an option

Provider JSON mode / response schema is recorded as an opt-in
option for JSON-returning agents. Default off; enabling it needs a
separate owner decision after measurement.

## Out of scope

- Changing models or model routing.
- Changing business prompt content.
- Touching S0 (spec 001), C1 (spec 005), or already-merged PRs.
