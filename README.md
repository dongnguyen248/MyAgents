# AI Software Agents

A reusable, project-independent platform for running an AI software development team.
Projects plug in through **project profiles** in `projects/`;
agents, workflows and infrastructure stay generic.

> Status: **core modules and Phase 7 agent logic implemented and tested with fakes**.
> Spec, Plan, Task, Implement, Review, Test and Fix agents exist. A Gemini gateway
> and separate manual smoke script are available. Phase 6 has a synchronous
> orchestrator with SQLite checkpoints, approval/revision, bounded retries,
> dependency-ordered task items, bounded Fix loops and event/metrics delivery ports.
> Phase 8 now includes Teams Workflows approvals without a custom bot:
> Reject with feedback revises the artifact; Approve automatically runs the next
> agent (see `src/asf/integrations/teams/README.md`).
> Real repository/sandbox adapters, GitLab/CI, distributed execution and
> backend-connected UI remain unfinished; Teams live deployment is not validated.
> Passing fake-driven tests does not establish live-chain or production readiness.

## Target workflow

```text
Requirement -> Spec -> [Approval] -> Plan -> [Approval] -> Task -> [Approval]
            -> Implement -> Code Review -> Test -> Quality Gate -> Git host -> CI -> Merge
```
Rejections loop back to the producing agent with feedback.

## Layout

| Path | Responsibility |
|---|---|
| `src/asf/` | Core Python package (`asf`): orchestrator, workflow, state machine, approval, evaluation, configuration, agents, integrations, models, contracts, tools, execution, storage, api, cli |
| `contracts/` | Language-neutral data contracts (JSON Schema Draft 2020-12) and port definitions |
| `apps/dashboard/` | Web UI "Control Tower" (React + TypeScript + Vite) for monitoring and managing agents, tasks, workflows and approvals |
| `skills/` | Reusable knowledge packages that projects enable/disable |
| `templates/` | Artifact templates (SPEC, PLAN, TASK, CODE_REVIEW, TEST_REPORT) |
| `projects/` | Project profiles (configuration only) |
| `harness/` | Agent evaluation and future self-improvement (Harness² research) |
| `tests/` | Platform tests, separate from agent evaluation |
| `docs/` | Architecture and design documentation |
| `scripts/` | Developer/ops helper scripts |
| `config/` | System configuration profiles |
| `docker/` | Container images and compose definitions |
| `examples/` | Sample projects and integration examples |

## Design rules
1. `src/asf/`, `contracts/`, `skills/` never reference a specific project.
2. Agents never call each other; the orchestrator mediates via artifacts + approvals.
3. Human approval is a platform capability, not part of any agent.
4. External services live behind interfaces in `src/asf/integrations/` and `src/asf/models/providers/`.
5. No LLM provider is hard-coded.
6. Agents never perform side effects (shell, git, network including LLM calls, filesystem, database) directly. They act only through ports defined in `contracts/ports.md`.

See [`docs/architecture/README.md`](docs/architecture/README.md).

## Python development checks

Install the optional Teams SDK when running the complete test suite:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,api]"
.\.venv\Scripts\python.exe -m pytest tests\ -x -q
.\.venv\Scripts\python.exe -m mypy src\ --strict
.\.venv\Scripts\python.exe -m ruff check src\ tests\
.\.venv\Scripts\python.exe -m bandit -r src\
```
