# Artifact-review fixtures

Offline, labelled artifacts for the `artifact-review` agent, added in
Phase 12 Stage E. They are **data only**: nothing in this directory is
executed, and the Harness² optimiser does not consume them yet. They
exist so a future offline evaluation (or a Harness² rollout adapter for
this agent) has known-good and known-bad review subjects per stage.

## Layout

- `manifest.json` — the index. Every fixture names its stage
  (`spec` / `plan` / `task`), a defect label, the artifact file, the
  upstream artifacts it is reviewed against (paths relative to this
  directory), and the expected outcome.
- `spec/*.md`, `plan/*.md` — markdown artifacts in the shape of the
  shipped SPEC / PLAN templates.
- `task/*.json` — TASK artifacts as the `{"tasks": [...]}` envelope the
  Task agent produces.

All fixtures describe one miniature project (a `textkit` CLI) so the
stages chain: the plan and task fixtures are reviewed against
`spec/good.md` (and `plan/good.md`).

## Expected outcomes

`expected.verdict` is the verdict a correct reviewer reaches.
`expected.mechanical` says whether the deterministic mechanical checks
(`src/asf/agents/artifact_review/checks.py`) alone must already produce
a BLOCKER finding; `expected.categories` lists the finding categories
the reviewer is expected to raise. Fixtures with `mechanical: false`
and a `REQUEST_CHANGES` verdict are judgement cases (vague criteria,
scope creep): the mechanical checks pass on them by design.

`tests/unit/test_harness2_artifact_review_fixtures.py` validates the
manifest and the mechanical expectations, so a fixture that silently
stops tripping its labelled defect fails the suite.
