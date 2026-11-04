# asf (AI Software Agents Core)

Platform-level package for the AI Software Agents. Contains no project-specific, vendor-specific or provider-specific code.

| Subpackage | Responsibility |
|---|---|
| `orchestrator/` | Coordinates agents (receive task, pick workflow, dispatch agent, collect artifact, request approval, handle rejection, continue) |
| `workflow/` | Declarative, reusable workflow definitions |
| `state_machine/` | States and legal transitions of a work item |
| `approval/` | Generic human-in-the-loop mechanism |
| `evaluation/` | Runtime metrics collection about agent performance |
| `configuration/` | Models and loaders for global/project/agent/workflow configuration |
| `agents/` | Reusable specialized agents (spec, plan, task, implement, review, test, fix) |
| `integrations/` | Adapters to external systems (GitLab, Teams, notifications, CI) |
| `models/` | Model gateway and provider adapters (`models/providers/`) |
| `contracts/` | Python data bindings and Pydantic schemas reflecting top-level `contracts/` |
| `tools/` | Tool definitions and execution adapters used by agents |
| `execution/` | Sandboxes, execution environments, and process runners |
| `storage/` | Persistence adapters for artifacts and operational data |
| `api/` | REST and streaming API serving the dashboard and clients |
| `cli/` | Command-line interface commands and utilities |
