# AI Software Factory

A reusable, project-independent platform for running an AI software development team.
Projects (VHPC, VNPC, ERP, internal apps, ...) plug in through **project profiles** in `projects/`;
agents, workflows and infrastructure stay generic.

> Status: **core contracts defined**. Agent logic, LLM, MCP, GitLab, Teams, CI, DB, auth and UI code are not implemented yet.

## Target workflow

```text
Requirement -> Spec -> [Approval] -> Plan -> [Approval] -> Task -> [Approval]
            -> Implement -> Code Review -> Test -> Quality Gate -> Git host -> CI -> Merge
```
Rejections loop back to the producing agent with feedback.

## Layout

| Path | Responsibility |
|---|---|
| `core/` | Platform engine: orchestrator, workflows, state machine, approval, evaluation, configuration, contracts |
| `agents/` | Reusable, independently structured agents (prompts, instructions, tools, skills, tests) |
| `skills/` | Reusable knowledge packages that projects enable/disable |
| `integrations/` | Adapters to external systems (GitLab, Teams, CI, LLM providers, ...) behind interfaces |
| `templates/` | Artifact templates (SPEC, PLAN, TASK, CODE_REVIEW, TEST_REPORT) |
| `projects/` | Project profiles (configuration only) |
| `harness/` | Agent evaluation and future self-improvement (Harness² research) |
| `tests/` | Platform tests, separate from agent evaluation |
| `docs/` | Architecture and design documentation |
| `scripts/` | Developer/ops helper scripts |

## Design rules
1. `core/`, `agents/`, `skills/`, `integrations/` never reference a specific project (e.g. VHPC).
2. Agents never call each other; the orchestrator mediates via artifacts + approvals.
3. Human approval is a platform capability, not part of any agent.
4. External services live in `integrations/` behind interfaces.
5. No LLM provider is hard-coded.

See [`docs/architecture/README.md`](docs/architecture/README.md).
