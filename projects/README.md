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
