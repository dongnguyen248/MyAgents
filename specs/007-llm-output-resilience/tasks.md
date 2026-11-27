# Tasks: LLM Output Resilience

Markers follow `docs/speckit-workflow.md`: `[ ]` pending, `[x]`
completed (with commit hash), `[~]` implemented locally but
unpushed, `[!]` awaiting owner decision.

## Phase A — R1 observability (separate PR, no behaviour change)

- [x] Owner reviews and approves spec 007 (spec, plan, tasks).
      Phase A implementation ordered by owner on 2026-11-26.
- [x] Shared evidence helper in `_shared` puts `replyChars`,
      `finishReason`, `repairsAttempted`, and a redacted excerpt
      into every `LLM_INVALID_RESPONSE` details (task,
      artifact-review, review, spec, plan). Superseded by
      decision C: the excerpt goes to a WARNING log line only.
      Test: a task JSON syntax error at a known offset yields
      details with all four fields, and the excerpt covers the
      offset region. (`04fa456`, `09dec11`, `bb063e4`, `4929d24`,
      `be13622`, `3ca4169`, `a79f656`, `6e20fe4`, `dd29565`)
- [x] Excerpt never leaks secrets.
      Test: a reply containing a secret-shaped string produces
      details/log with the secret redacted (attack case).
      (`854f1f2`)
- [x] Regression: valid replies behave exactly as before.
      Test: existing spec/plan/task/artifact-review suites pass
      unchanged; golden prompts untouched. (`602620f`, `0a62b18`,
      `4fc5daa`, `827024f`, `4ac183b`, `b08c71b`, `e886d80`)
- [x] Run full gates (ruff, format, mypy, bandit, pytest, ratchet,
      gitleaks) and report real output. (`e886d80`; gitleaks not
      available in sandbox)
- [x] Owner decided C on 2026-11-26: error details carry only
      `replyChars`/`finishReason`/`repairsAttempted`; the redacted
      excerpt (at most 160 characters) goes only to a separate
      WARNING log line, never through details; the old
      `test_review_agent.py` no-echo assertions are restored.
      (`a2e550e`, `2a22ff5`, `cf7d3c4`, `82994b5`, `9c9a226`,
      `271de2b`, `f7aff8a`, `1528c0e`, `c8de73b`)

## Phase B — R2/R3 (starts only after Phase A log evidence)

- [ ] Waiting for data: collect Phase A excerpts from real
      failures; confirm or refute H1 (prose/fence wrapping) and
      the task-agent alternative hypothesis (unescaped string /
      missing comma).
- [ ] R2: shared retry-with-feedback, at most 1 retry,
      generalizing `repair.py` and `ebe9af5`.
      Test: an invalid JSON reply triggers exactly one retry whose
      feedback carries the parse error; a valid second reply
      succeeds; a second failure raises with `repairsAttempted=1`.
- [ ] R2 truncation guard: `finishReason=length` is never retried
      as a repair.
      Test: a truncated reply fails immediately with
      `repairsAttempted=0` and the truncation remedy, no repair
      call made.
- [!] Separate decision: enable a step `retryPolicy` for the task
      step (today absent, `software-development.yaml:34`), distinct
      from retry-with-feedback.
- [ ] R3: extract one unambiguous `{...}` block for task,
      artifact-review, review; no guessed JSON repair. Fence
      stripping already exists everywhere and is not redone.
      Test: prose around one object parses; JSON needing an
      inserted comma still fails into R2/R1 instead of parsing
      silently.

## R4 — option only

- [ ] Provider JSON mode recorded as an opt-in option, default
      off.
      Test: settings default has JSON mode disabled; no request
      carries a JSON-mode parameter while disabled.
