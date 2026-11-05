# Platform Error Codes

In the `PlatformError` schema, `code` is an open string to allow components, plugins, and custom integrations to report specialized failure modes without requiring central schema changes. Namespaced codes (e.g. `CUSTOM_PLUGIN_TIMEOUT`) are recommended for non-standard extensions.

Below is the standard catalog of built-in platform error codes. Each code maps to a valid `PlatformError.category`, specifies a default `retryable` status, and describes the error condition.

| code | category | retryable default | meaning |
|---|---|---|---|
| NOT_FOUND | SYSTEM | false | requested resource does not exist |
| VALIDATION_FAILED | VALIDATION | false | request or payload failed validation |
| INTERNAL_ERROR | SYSTEM | false | unexpected internal failure |
| AGENT_NOT_REGISTERED | AGENT | false | no agent registered for the given id or type |
| AGENT_EXECUTION_FAILED | AGENT | true | agent raised or returned a failure |
| WORKFLOW_INVALID_TRANSITION | WORKFLOW | false | state transition not allowed |
| WORKFLOW_STEP_TIMEOUT | WORKFLOW | true | step exceeded its timeout |
| RUN_BUDGET_EXCEEDED | WORKFLOW | false | run's accumulated model usage exceeded the configured RunBudget; stopped before the next dispatch |
| APPROVAL_EXPIRED | APPROVAL | false | decision arrived after expiresAt |
| APPROVAL_ALREADY_DECIDED | APPROVAL | false | a decision already exists, or the reviewer already approved |
| APPROVAL_NOT_AUTHORIZED | APPROVAL | false | reviewer is not allowed to decide this approval |
| INTEGRATION_UNAVAILABLE | INTEGRATION | true | external integration unreachable |
| LLM_TIMEOUT | LLM | true | model call timed out |
| LLM_RATE_LIMITED | LLM | true | model provider throttled the call |
| LLM_INVALID_RESPONSE | LLM | true | model output unusable or unparsable |
| LLM_OUTPUT_TRUNCATED | LLM | true | model output cut off by the output token limit (finish_reason length/MAX_TOKENS); retry with a higher max_tokens or a smaller task |
| LLM_AUTH_FAILED | LLM | false | provider rejected the credentials (HTTP 401/403) |
| LLM_CONTEXT_TOO_LONG | LLM | false | request exceeds the model's context window |
| LLM_BAD_REQUEST | LLM | false | provider rejected the request as invalid (other 4xx) |
| GIT_CONFLICT | GIT | false | merge or push conflict |
| GIT_OPERATION_FAILED | GIT | true | source-control operation failed |
| CI_RUN_FAILED | CI | false | pipeline finished with failure |
| CI_UNAVAILABLE | CI | true | CI system unreachable |
| REPOSITORY_ERROR | INTEGRATION | true | repository port read/list failure |
| SANDBOX_ERROR | INTEGRATION | true | sandbox infrastructure failure |
| COMMAND_TIMEOUT | INTEGRATION | true | command exceeded its timeout |
