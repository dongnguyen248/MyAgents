# ASF Constitution

Derived from `AGENTS.md` and `docs/architecture/README.md`. Where
this file and those sources disagree, those sources win.

## Platform design rules

1. `src/asf/`, `contracts/`, `skills/` and `workflow-definitions/`
   never reference a specific project.
2. Agents never call each other; the orchestrator mediates via
   artifacts and approvals.
3. Human approval is a platform capability, not part of any agent.
4. External services live behind interfaces in
   `src/asf/integrations/` and `src/asf/models/providers/`.
5. No LLM provider is hard-coded.
6. Agents never perform side effects directly; they act only
   through ports, wired in by the orchestrator.
7. Configuration never contains secret values; credentials are
   environment-variable references resolved by adapters at use.
8. The state machine is pure; stage lists are generated from
   workflow definitions, never hard-coded.
9. Time and identifiers are injected; engines and agents never
   read the clock or generate ids.

## Code structure

- Functions ≤ 30 lines, ≤ 4 parameters, nesting ≤ 3, complexity
  ≤ 10. Classes ≤ 300 lines, ≤ 10 public methods, ≤ 7 fields.
  Files ≤ 500 lines. No mixin splits; extract collaborators.
- No magic values; braces on every control-flow block; one
  statement per line; no nested ternary beyond a single trivial
  one; comments only for non-obvious WHY.
- The ratchet baseline only shrinks: new or grown violations fail.

## Verification

- Before reporting: `ruff check src tests`,
  `ruff format --check src tests harness`, `mypy src --platform
  linux`, `bandit -c .bandit -r src -q`, ratchet, `pytest -q`,
  demo selftest; dashboard `npm test`, `npm run build`, lint.
  Report real results only; "done" without output is not done.
- New tests for every behaviour change; never weaken old tests.
- Test suites run only in a clean clone/worktree with its own
  venv.

## Security

- No secrets in chat, code, tests, fixtures, profiles, or zips;
  at most configuration status plus a last-4 hint.
- Fail closed; least privilege; validate external input; reuse
  `scan_secrets`/`redact_text`; every PR carries a
  `Security impact:` line.

## Delivery discipline

- Commit per file, never `git add -A`; preserve file EOL; never
  rebase `88f2840` or earlier; pushes are fast-forward.
- No push and no PR without Dong's explicit order for that push
  or PR. Dong creates and merges PRs.
- Public-contract changes update JSON Schema, Python models,
  dashboard TS types, and tests together.
- Reports state deviations honestly ("Lệch dự kiến"), including
  when a premise in the brief was wrong.
