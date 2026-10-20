# core/
Platform-level functionality. Contains no project-specific, vendor-specific or provider-specific code.

| Dir | Responsibility |
|---|---|
| orchestrator/ | Coordinates agents (receive task, pick workflow, dispatch agent, collect artifact, request approval, handle rejection, continue) |
| workflow/ | Declarative, reusable workflow definitions |
| state-machine/ | States and legal transitions of a work item |
| approval/ | Generic human-in-the-loop mechanism |
| evaluation/ | Runtime metrics collection about agent performance |
| configuration/ | Models and loaders for global/project/agent/workflow configuration |
| contracts/ | Interfaces and schemas shared by everything (agent I/O, artifacts, approval requests, events) |
