# ArtifactReviewAgent

Phase 12 reviewer for the document approval gates. It consumes exactly one
SPEC, PLAN, or TASK artifact (selected by `input.stage`), its upstream
approved artifacts (SPEC for plan; SPEC + PLAN for task), and optionally the
previous round's ARTIFACT_REVIEW. Requests failing validation are rejected
before any check or model call.

`ArtifactReviewAgent(runtime, settings=ArtifactReviewSettings(prompts=...))`
uses only the runtime model gateway, at most once per execution. The factory
`build_artifact_review_agent(runtime, platform, templates_dir)` loads the
packaged prompts and the optional `artifact-review` model profile.

Two layers decide a round:

1. **Mechanical checks** (`checks.py`) run first and never call the model:
   template sections present and non-empty, REQ-<n> ids defined once and
   covered by acceptance criteria (SPEC), SPEC coverage and no unknown
   references (PLAN), and task shape, dependency DAG, traceability,
   expected-file safety, and the task cap (TASK). A mechanical BLOCKER
   short-circuits the round and is returned as the round's findings.
2. **The model** returns findings only — never a verdict. `ArtifactReviewContent`
   is strict (unknown fields, including a model-supplied `verdict`, are
   rejected): at most 20 findings, each with severity, category, location,
   a concrete problem and an actionable required change; WAIVED requires a
   reason and a BLOCKER can never be WAIVED.

The verdict is derived in code (`verdict.py`): APPROVE iff no open finding's
severity is in the configured `blockOn` set (default BLOCKER + MAJOR).
Previous findings the model does not mention are carried forward as
STILL_OPEN, so problems cannot be dropped by silence; from round 2, NEW
MINOR/NIT findings from the model cannot block (bias guard). The same module
detects stagnation (identical artifact, or an unchanged blocking set with a
barely-changed artifact) and regressions (RESOLVED findings open again).

Success creates one ARTIFACT_REVIEW artifact with the structured `review`,
deterministic Markdown `text`, and metadata naming the reviewed artifact id
and version, the stage, the round, the derived verdict, per-severity counts
and the finding ids. Output contains the verdict; the orchestrator owns
state-machine transitions and approval decisions.

The agent is registered on the Harness² surface
(`harness/harness2/surface.py`): `prompts/system.md`,
`instructions/guardrails.md`, `instructions/memory.md`, agent skills, and
the three stage checklists are editable; `prompts/contract.md` is frozen,
and `verdict.py` / `checks.py` are code, never harness files. Offline
labelled fixtures for future evaluation runs live in
`harness/harness2/fixtures/artifact-review/`. The operator-facing
reference for the whole loop is `docs/ai-review-approval.md`.
