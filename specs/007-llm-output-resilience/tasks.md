# Tasks: LLM Output Resilience

Markers follow `docs/speckit-workflow.md`: `[ ]` pending, `[x]`
completed (with commit hash), `[~]` implemented locally but
unpushed, `[!]` awaiting owner decision.

- [ ] Owner reviews and approves spec 007 (spec, plan, tasks).
- [ ] R1: shared evidence helper in `_shared` puts `replyChars`,
      `finishReason`, `repairsAttempted`, and a redacted excerpt
      into every `LLM_INVALID_RESPONSE` details (task,
      artifact-review, review, spec, plan).
      Test: a task JSON syntax error at a known offset yields
      details with all four fields, and the excerpt covers the
      offset region.
- [ ] R1 security: excerpt never leaks secrets.
      Test: a reply containing a secret-shaped string produces
      details/log with the secret redacted (attack case).
- [ ] R2: shared retry-with-feedback, at most 1 retry, generalizing
      `repair.py` and `ebe9af5`.
      Test: an invalid JSON reply triggers exactly one retry whose
      feedback carries the parse error; a valid second reply
      succeeds; a second failure raises with `repairsAttempted=1`.
- [ ] R2 truncation guard: `finishReason=length` is never retried
      as a repair.
      Test: a truncated reply fails immediately with
      `repairsAttempted=0` and the truncation remedy, no repair
      call made.
- [ ] R3: light preprocessing strips code fences and extracts one
      unambiguous `{...}` block; no guessed JSON repair.
      Test: fence-wrapped JSON parses with 0 retries; prose around
      one object parses; JSON needing an inserted comma still
      fails into R2/R1 instead of parsing silently.
- [ ] R4: provider JSON mode recorded as an opt-in option,
      default off.
      Test: settings default has JSON mode disabled; no request
      carries a JSON-mode parameter while disabled.
- [ ] Regression: valid replies behave exactly as before.
      Test: existing spec/plan/task/artifact-review suites pass
      unchanged; golden prompts untouched.
- [ ] Run full gates (ruff, format, mypy, bandit, pytest, ratchet,
      gitleaks) and report real output.
