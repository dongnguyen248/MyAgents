# src/asf/agents/

Reusable agent implementations and base abstractions.

## Agent Structure

Each agent package adheres to a uniform structure:

```text
<agent>/
├── README.md        purpose, input/output contract, boundaries
├── __init__.py      package exports
├── agent.py         agent implementation inheriting from BaseAgent
├── factory.py       factory / builder for creating configured instances
├── prompts/         provider-neutral prompt templates (markdown)
├── instructions/    behavioural rules and guidelines
├── tools/           tool declarations (via contracts)
├── skills/          skill declarations / overrides
└── tests/           agent-level tests and evaluation cases
```

## Lifecycle

Agents follow a strict two-stage execution lifecycle:

1. **Validation (`validate(request: AgentRequest) -> ValidationResult`):**
   Validates inputs, configuration, required fields, and constraints before any execution or model call takes place. Returns `{ valid: boolean, errors: PlatformError[] }`. If invalid, `execute()` is not invoked.

2. **Execution (`execute(request: AgentRequest) -> AgentResult`):**
   Executes the task, interacts with language models via the injected `ModelGateway`, produces artifacts, emits lifecycle activity events, and records `RunMetrics`.

### Execution Statuses

The result status (`AgentResult.status`) can be one of:
- `SUCCESS`: Task completed successfully and expected artifacts were produced.
- `FAILED`: Execution failed due to a model gateway error or unexpected exception.
- `REJECTED`: The request was refused by validation (no gateway call, no events).

## Runtime Injection

Agents never create side effects, read system clocks, or generate identifiers on their own. Instead, an `AgentRuntime` instance is injected into the agent constructor:

- `models`: Injected `ModelGateway` implementation for completing model requests.
- `clock`: Injected function returning a timezone-aware `datetime` (UTC).
- `new_id`: Injected function producing unique identifiers (e.g. for events and artifacts).

## Dependency Rules

To preserve isolation and modularity:
1. **Allowed imports:**
   - Standard library modules
   - `asf.contracts` (data contracts and Pydantic models)
   - `asf.models` (model gateway port, errors, fakes)
   - The agent's own submodules (prompts, instructions, helpers)
2. **Prohibited imports:**
   - No imports of orchestrator, state machine, approval service, storage backends, integration adapters, or project profiles.
   - No direct network, filesystem, or operating system calls.
3. **Side effects only via ports and result:**
   - Language model calls must go through `ModelGateway`.
   - Events and artifacts are returned on `AgentResult` for the orchestrator to publish and persist.

