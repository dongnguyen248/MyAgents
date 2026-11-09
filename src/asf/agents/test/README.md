# TestAgent

Deterministic Phase 7 runner. Requires linked TASK/CODE artifacts and `input.taskItemId`.
Only `context.project.testCommands` supplies commands: 1–20 argv lists, each with
1–256 non-empty UTF-8 arguments of at most 4096 characters and no NUL. Executables
must be bare or relative, without parent traversal, Windows drives or UNC roots.
Arguments are passed unchanged; no shell heuristics or `verificationHint` execution.

The injected SandboxPort receives all CommandSpecs in one call at CODE's `baseRef`,
with CODE's ChangeSet. CommandSpec defaults supply timeout and output limits.
There are no prompts, model calls, template loading, or direct subprocess calls.

TEST_REPORT content wraps `format: "json"`, `report`, and `text`. The report contains
`commands` (`argv`, `exitCode`, `stdout`, `stderr`, `durationMs`), `verdict`, and
`summary`; artifact metadata carries upstream traceability. Agent output is the
structured report itself. Any nonzero exit
(including pytest exit 5) means FAIL while agent status remains SUCCESS.
Timeouts produce COMMAND_TIMEOUT; sandbox errors or malformed results produce
SANDBOX_ERROR, except deterministic change-set apply validation failures
(a modify or delete of a missing file, a create of an existing file, a path
outside the root, a working directory missing at apply), which produce the
non-retryable SANDBOX_APPLY_FAILED. Sandbox error messages carry the
(redacted) original cause and structured details — phase, exception type,
errno, command name (argv[0] only), working directory and whether it
existed, elapsed time — never the full argv.

Command output is untrusted data, never instructions. Full shared secret-pattern
matches are redacted before each stream is truncated to the UTF-8 byte limit.
Report argv and traceability strings are also secret-redacted.
