# Project Profiles (`projects/`)

This directory contains project profile configuration files (`<project-id>.yaml` or `<project-id>.yml`).
Project profiles define project metadata, technology stacks, workflows, and configuration options.
They are configuration only: no executable code, and no literal secret values.

## Format Specification

Keys in a project profile YAML file map directly (1:1) to the `Project` contract schema.

### Required Fields
- `name` (string): Human-readable name of the project.
- `repository` (object): Repository configuration (e.g., provider, URL, branch).
- `technology` (object): Technology stack definitions (e.g., backend, frontend, language/framework selections).
- `workflow` (string): Workflow definition name to execute for the project (e.g., `software-development`).

### Optional Fields and Defaults
- `id` (string, optional): Unique project identifier. Defaults to the filename stem (e.g., `<project-id>` from `<project-id>.yaml`). If explicitly provided, it **must** equal the filename stem.
- `description` (string, optional): Description of the project. Defaults to `""`.
- `enabledAgents` (array of strings, optional): List of agent identifiers enabled for this project. Defaults to `[]`.
- `enabledSkills` (array of strings, optional): List of skill identifiers enabled for this project. Defaults to `[]`.
- `configuration` (object, optional): Project-specific configuration mapping (e.g., approval channels, custom parameters). Defaults to `{}`.
- `status` (string, optional): Lifecycle status. Allowed values: `ACTIVE`, `INACTIVE`, `ARCHIVED`. Defaults to `ACTIVE`.

### Secret Handling Rule
Project profiles are subject to automated secret scanning:
- Secret keys (keys ending in `secret`, `token`, `password`, `passwd`, `api_key`, `apiKey`, or `credentials`) must **never** contain literal secret strings or values.
- Literal secrets are strictly rejected.
- To reference a secret, use an environment reference object `{env: ENV_VAR_NAME}` or set the field to `null`.

## Example Profile

```yaml
# <project-id>.yaml
# id is optional and defaults to the file stem ("<project-id>")
name: Example Project
description: "Demonstration project configuration profile."

repository:
  provider: git
  url: "https://example.com/org/example-repo.git"
  token:
    env: GIT_REPO_TOKEN

technology:
  backend: [python]
  frontend: [react]

workflow: software-development

enabledAgents:
  - developer
  - reviewer

enabledSkills:
  - git
  - testing
  - security

configuration:
  approval:
    channel: slack

status: ACTIVE
```

## Approval settings

Project profiles can configure human approval policies under `configuration.approval`:

- `reviewers` (required list of non-empty strings): Authorized reviewer identifiers. Real reviewer identifiers will be mapped when the channel adapter is configured (Phase 8); currently neutral identifiers (e.g., `reviewer-1`) are used in tests. No real reviewer identifiers exist in existing project profiles yet.
- `minApprovals` (optional integer >= 1, default 1): Number of distinct reviewer approvals required to transition an approval to `APPROVED`. Must be `<= len(reviewers)`.
- `expiresInSeconds` (optional integer >= 1 or null, default null): Time-to-live for pending approval requests. `null` means the approval does not expire.
- `channel` (optional mapping or string): Target notification channel metadata (e.g., Teams channel configuration). Passed through and consumed by notification adapters.

### Example configuration

```yaml
configuration:
  approval:
    channel: teams
    reviewers:
      - reviewer-1
      - reviewer-2
    minApprovals: 1
    expiresInSeconds: 86400
```

