# src/asf/workflow/

## Responsibility
The `asf.workflow` package provides models, loaders, and validations for reusable, declarative workflow definitions. Workflow definitions are project-independent data models that describe a pipeline of steps, artifact flows, and approval gates.

Planned workflow definitions: `bug-fix`, `feature-development`, `refactoring` (not defined yet).
Current reference definition: `software-development` (located in `workflows/software-development.yaml`).

## Definition Format
Workflow definition files (`workflows/*.yaml` or `*.yml`) use field names identical to the contract schemas under `$defs/Workflow` and `$defs/WorkflowStep`:
- `id` (string, matches file stem)
- `name` (string)
- `version` (string)
- `metadata` (object, defaults to `{}`)
- `steps` (array of step definitions, in execution order)

Each step definition includes:
- `id` (string, unique within workflow)
- `name` (string)
- `type` (string minLength 1; standard values are `AGENT`, `APPROVAL`, `SYSTEM`, and `INTEGRATION`; custom step types are allowed)
- `stage` (base stage name matching `^[A-Z][A-Z0-9_]*$`)
- `requiresApproval` (boolean)
- `agentType` or `action` (at least one required)
- `timeout` (optional integer seconds, >= 1)
- `retryPolicy` (optional retry policy)
- `configuration` (optional object, defaults to `{}`)
- `consumes` (optional list of artifact type strings)
- `produces` (optional list of artifact type strings)
- `maxRevisions` (optional integer >= 0, meaningful and allowed only when `requiresApproval` is `true`)

## Defaults
- `id`: Inferred from the file stem if omitted. If explicitly specified, it must match the file stem.
- `metadata`: Defaults to `{}`.
- `maxRevisions`: For approval steps (`requiresApproval: true`) where `maxRevisions` is omitted, it resolves to `DEFAULT_MAX_REVISIONS = 3`.
- No other defaults are applied.

## Validation Rules
All validation failures produce `ConfigError` with dotted issue paths:
1. `steps` must contain at least one step.
2. Step IDs must be unique within the workflow.
3. Step `stage` must match `^[A-Z][A-Z0-9_]*$`.
4. Each step must specify at least one of `agentType` or `action`.
5. `maxRevisions` is permitted only on steps where `requiresApproval` is `true`.
6. Generated stage names across all steps must be unique and must not conflict with reserved global stage names (`NEW`, `COMPLETED`, `FAILED`, `CANCELLED`).
7. Every consumed artifact type in `consumes` must have been produced by an earlier step (never by the same or a later step).
8. Strict YAML loading rejects duplicate keys and non-mapping root documents.
