# ReviewAgent

Phase 7 reviewer consumes exactly one SPEC, PLAN, TASK, and CODE with matching
task-item and upstream traceability. CODE uses the shared ChangeSet validator.
Requests failing validation are rejected before any model call.

`ReviewAgent(runtime, prompts=ReviewPrompts(system=...), model=None, parameters=None)`
uses only the runtime model gateway, once per execution. The factory
`build_review_agent(runtime, platform, templates_dir)` loads the packaged system
prompt and optional `review` model profile; no artifact template is needed.

Replies contain `findings` and `verdict` (`APPROVE` or `CHANGES_REQUESTED`).
Findings require severity (`ERROR`, `WARNING`, `INFO`), a CODE path, and a
nonblank description; optional line numbers are positive integers and optional
suggestions must be nonblank. Unknown fields, more than 100 findings, paths
outside CODE, and APPROVE with ERROR are invalid. Raw replies and rendered text
are bounded by shared limits. Invalid responses fail non-retryably with
`LLM_INVALID_RESPONSE`, without exposing parser errors or raw payloads.

Success creates one schema-valid CODE_REVIEW artifact with structured `review`,
deterministic Markdown `text`, and injected upstream/CODE traceability.
Output contains the verdict; the orchestrator owns state-machine transitions.
Enabled skill names appear on exactly one system-prompt line; skill content
is never loaded. No repository reads, sandbox execution, or real API is required
by the fake-driven unit tests.
