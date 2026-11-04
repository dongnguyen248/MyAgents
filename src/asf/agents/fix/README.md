# FixAgent

Consumes SPEC, PLAN, TASK, exactly one CODE, and one or more linked CODE_REVIEW
or TEST_REPORT artifacts. Rejects stale CODE IDs/versions, mismatched task items,
duplicate reports and a ref different from the original CODE baseRef.

Produces a complete replacement CODE (not an incremental patch), increments the
CODE version, and records revisionOf, fixedReviewIds and fixedTestReportIds.
The original repository is read through RepositoryPort and is never mutated.
Generated files use the same shared scope, size, existence and secret checks as
ImplementAgent.

Use build_fix_agent(runtime, platform, templates_dir, repository). Prompts are
packaged resources; model calls go only through the injected runtime gateway.
No orchestrator, repository adapter or sandbox implementation is provided here.
