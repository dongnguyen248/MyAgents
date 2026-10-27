# contracts/

**Responsibility:** Python data contracts and Pydantic models reflecting top-level `contracts/schemas/contracts.schema.json`.

## Pydantic Bindings

The following Pydantic models in `asf.contracts.models` bind to the canonical JSON Schema `$defs`:

- `AgentMetadata`
- `AgentStatus`
- `AgentRequest`
- `AgentResult`
- `RunMetrics`
- `Artifact`
- `ActivityEvent`
- `PlatformError`
- `ModelRequest`
- `ModelResponse`
- `ModelConfig`
- `ModelUsage`

All models support serialization to/from JSON and Python dictionaries, with validation against field constraints and enums defined in the schema.

### Helper: `to_contract`

`to_contract(model_instance)` converts a Pydantic model instance into a canonical camelCase dictionary suitable for serialization over ports, event streams, or JSON persistence, matching schema definitions exactly.

### Drift Guard

The test suite in `tests/unit/test_contract_bindings.py` enforces a bidirectional schema drift guard:
1. Every model field is checked against the corresponding `$defs` property in `contracts/schemas/contracts.schema.json`.
2. Model fields must preserve required fields, types, and allowed values.

### Dependency Note

`ApprovalFeedback`, `ApprovalRequest`, `ApprovalDecision`, and `ApprovalPolicy` currently reside in `asf.approval.models` (Phase 4). When all approval bindings are consolidated into `asf.contracts` in a later phase, they will be exported from here.
