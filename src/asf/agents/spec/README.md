# agents/spec/

**Responsibility:** Transforms a raw requirement into a structured, validated `SPEC` artifact.

## Input Contract

The Spec Agent accepts an `AgentRequest` with:
- `request.input["requirement"]` (string, required): The requirement text describing the feature or change.
- `request.input["context"]` (dict, optional): Supplementary context, technical constraints, or architectural notes.
- `request.feedback` (list of `ApprovalFeedback`, optional): Reviewer feedback from previous approval cycles requiring revision.
- `request.artifacts` (list of `Artifact`, optional): Artifacts from prior iterations (e.g. earlier draft `SPEC` artifact).
- `request.model` (`ModelConfig`, optional): Model parameters (model ID, temperature, etc.).

## Validation Rules

`validate(request: AgentRequest)` checks the following:
1. `request.input` must be a dictionary.
2. `request.input["requirement"]` must be a non-empty string.
3. Length of `requirement` must not exceed `MAX_REQUIREMENT_CHARS` (10,000 characters).
4. `request.input["context"]` (if provided) must be a dictionary.
5. `request.model` (if provided) must be a valid `ModelConfig`.

If validation fails, a `ValidationResult` is returned with `valid=False` and standard `PlatformError` entries (`VALIDATION_ERROR`).

## Prompts & Templates

### Prompt Sections
- **System Prompt (`prompts/system.md`):** Defines the Spec Agent role, instructions for generating specifications conforming to the standard template, formatting rules, and strict instructions to match the language of the requirement.
- **Revision Prompt (`prompts/revision.md`):** Used during revision iterations; instructs the model to preserve accepted sections while specifically addressing reviewer feedback.
- **User Prompt (`build_user_prompt` in `prompts.py`):** Assembles the requirement, context, and template into the final user prompt.

### Standard Template
Loaded via `load_spec_template()` (from built-in template resources or root `templates/spec/SPEC.md`). The generated output must include all 7 required top-level sections:
1. `## 1. Overview`
2. `## 2. Requirements & Acceptance Criteria`
3. `## 3. Architecture & Design`
4. `## 4. API & Interface Contracts`
5. `## 5. Non-Functional Requirements`
6. `## 6. Dependencies & External Integrations`
7. `## 7. Open Questions & Risks`

## Artifact Format

Upon successful execution, the agent produces an `Artifact`:
- `type`: `"SPEC"`
- `name`: `"SPEC.md"`
- `content`: `{"format": "markdown", "text": "<generated markdown content>"}`
- `metadata`: `{"attempt": attempt, "revision": is_revision, "template_validated": True}`

## Revision Flow

When `request.feedback` contains reviewer comments or `request.artifacts` contains a previous `SPEC` artifact:
1. The agent identifies the execution as a revision (`is_revision = True`).
2. Prior feedback comments and previous specification content are injected into the revision prompt.
3. The generated artifact records revision metadata and incremented attempt counters.

## Language Rule

The Spec Agent strictly respects the language of the provided requirement. For instance, if the requirement is written in Vietnamese, the resulting specification is produced in Vietnamese; if written in English, the specification is produced in English.

## Events, Metrics & Errors

- **Activity Events:** Emits `agent.started` at execution beginning, and `agent.completed` or `agent.failed` upon termination.
- **Run Metrics:** Returns `RunMetrics` tracking `duration_seconds`, `revision_count`, `attempt`, `tokens_used`, and `cost_usd`.
- **Platform Errors:** Maps errors into standard codes:
  - `VALIDATION_ERROR`: Input failed validation checks.
  - `LLM_TIMEOUT`: Model call timed out.
  - `LLM_INVALID_RESPONSE`: Model response failed template validation or was corrupted.
  - `AGENT_EXECUTION_FAILED`: General unhandled execution error.
