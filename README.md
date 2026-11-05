# AI Software Agents

A reusable, project-independent platform for running an AI software development team.
Projects plug in through **project profiles** in `projects/`;
agents, workflows and infrastructure stay generic.

> Status: **local implementation and integration work in progress, not production-ready**.
> Seven agents are implemented, not just Spec. Tests and the demo use scripted
> components for some workflows; real integrations exist in code but their
> presence does not establish end-to-end or production readiness. See the
> module status below for the implemented scope and its limits.

## Implementation status

**Implemented** means code exists for the scope described, not that every
integration has been validated live. **Contract only** means an interface or
placeholder exists without a corresponding implementation in that module.
**Planned** means the capability is not implemented. Each row describes its
own scope; a module can still have planned capabilities.

| Module | Status | Current scope and limitations |
|---|---|---|
| `agents` | Implemented | Spec, Plan, Task, Implement, Review, Test and Fix. Test runs commands through a sandbox port; other agents use injected ports. Fake-driven tests do not establish live-chain readiness. |
| `orchestrator` | Implemented | Local synchronous workflow execution, approval/revision, retries, fix loops and checkpoints; no distributed scheduler. |
| `workflow` | Implemented | Declarative workflow definitions and execution model; additional workflows remain planned. |
| `state_machine` | Implemented | Workflow-derived stages and transitions. |
| `approval` | Implemented | Approval policies, decisions and feedback; separate from application authentication. |
| `configuration` | Implemented | Platform configuration and project profiles. |
| `contracts` | Implemented | Python models and language-neutral schemas and ports; a port does not imply a live adapter. |
| `models` | Implemented | Gateway contract and scripted gateway; provider adapters live in `integrations`. |
| `integrations` | Implemented | LLM, hosting and Teams adapters exist; see the integration status below for their boundaries. |
| `tools` | Implemented | Repository and sandbox ports, fakes and local workspace adapters. Local commands run in a trusted workspace, not an isolation sandbox. |
| `execution` | Contract only | Placeholder for execution isolation and runtime runners; no isolated execution implementation in this package. |
| `storage` | Implemented | In-memory, SQLite and MariaDB execution storage; SQLite is a local single-worker store, not a distributed persistence claim. |
| `evaluation` | Implemented | Runtime metrics and aggregation; metrics are not a substitute for an independent quality benchmark. |
| `api` | Implemented | FastAPI REST/SSE adapter and demo assembly for the dashboard; not a production security boundary. |
| `cli` | Implemented | Minimal console entry point: `asf --version` and `asf serve` (runs the demo server, passing its flags through). A general platform CLI is not implemented. The offline harness has a separate CLI. |

### Integrations and applications

| Capability | Status | Current scope and limitations |
|---|---|---|
| LLM | Implemented | Gemini and OpenAI-compatible gateways exist alongside a scripted gateway. Live provider availability and full-chain behavior depend on configuration and have not been established by fake-driven tests. |
| MCP | Planned | No MCP integration is claimed. |
| GitLab / CI | Implemented | Hosting adapters and workflow actions exist. The CI action succeeds when hosting is unconfigured or no pipeline exists, so it is not a mandatory quality gate; live behavior and production readiness are not established. |
| Teams | Implemented | Teams Workflows approval adapter and authenticated callback exist; deploying the external flow and live validation remain outstanding. |
| Database | Implemented | SQLite and MariaDB execution stores exist; MariaDB requires a configured server. Neither implies distributed execution readiness. |
| Authentication / authorization | Planned | General API user authentication and authorization are not established; the Teams callback's authentication is specific to that integration. |
| Dashboard | Implemented | React UI can use mock data or the HTTP/SSE backend. The backend demo and integrations are not a production deployment. |
| Offline harness | Implemented | Scripted Spec/Plan evaluation and a deterministic fix-cycle experiment exercise orchestration; their scores do not independently establish artifact quality or optimal configuration. |
| Harness² integration | Contract only | Optional adapter protocol, null default and local rules exist; Google Harness² is not integrated. |

Architecture documents describe both current behavior and intended design; use
this status table and the linked module documentation to distinguish them.

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

## Sandbox trust model

The sandbox runs **the project operator's own commands**, and it is
important to be precise about what that means:

- Test commands come from the project profile
  (`configuration.testCommands`), i.e. from whoever configures the
  project — never from model output. The model's changeset can only
  create/modify/delete files (path-validated, secret-scanned); it
  cannot choose commands.
- Commands run with `shell=False` and a validated argv (no shell
  interpolation), as the backend process's own user, **with that
  user's privileges**. The sandbox is not a jail: a malicious
  profile is a malicious command. Only configure projects you trust.
- What the sandbox does protect against is accidents and leakage:
  a scrubbed environment (allowlist only; no `ASF_*` backend
  secrets reach test processes), CPU/memory/file-size limits,
  output caps, a throwaway per-run HOME, process-tree termination
  on timeout, and — for git projects — all file writes land in a
  per-run git **worktree**, never in the operator's working tree,
  so a failed or cancelled run leaves the real tree untouched.

## Environment variables

Configuration files never contain secrets; they reference these
variables (or the backend's own settings stores):

| Variable | Purpose |
| --- | --- |
| `ASF_MARIADB_HOST` / `ASF_MARIADB_PORT` / `ASF_MARIADB_USER` / `ASF_MARIADB_PASSWORD` / `ASF_MARIADB_DATABASE` | MariaDB run store (demo `--mariadb`); the demo also loads the repo-root `.env` |
| `ASF_GITLAB_TOKEN` / `ASF_GITHUB_TOKEN` | Fallback hosting tokens (a per-project token stored via the dashboard wins; `repository.tokenEnv` can name a different variable per project) |
| `ASF_MODEL_SETTINGS_FILE` | Where the dashboard's model settings (provider/model/key) persist; defaults to `model-settings.json` beside the run database |
| `ASF_HOSTING_TOKENS_FILE` | Same, for per-project hosting tokens (`hosting-tokens.json`) |
| `ASF_LOG_LEVEL` | Backend console log level for the `asf` namespace (default INFO) |
| `ASF_TEST_MARIADB` | Test-only: set to `1` to run the MariaDB integration tests |
| `ASF_LIVE_GEMINI_API_KEY` / `ASF_LIVE_GEMINI_MODEL` | Test-only: credentials for the opt-in live Gemini tests |

## Configuration notes

All three live in `config/platform.yaml` (see
`config/platform.example.yaml` for the annotated form):

- **Concurrency** — `execution.maxConcurrentRuns` (default 2) bounds
  both how many runs the service drives at once and how many model
  calls may be in flight; raise it only together with the model
  provider's rate limits.
- **Run budget** — the `budget:` block (`maxPromptTokens`,
  `maxCompletionTokens`, `maxModelCalls`; any may be omitted =
  unlimited) fails a run with `RUN_BUDGET_EXCEEDED` before the
  dispatch that would cross the cap, instead of calling the model
  again. Token counts come from the providers' own usage reports.
- **Edit format** — `agents.implement.settings.editFormat` and
  `agents.fix.settings.editFormat` choose how code agents write
  changes: `blocks` (default; SEARCH/REPLACE blocks, far fewer
  output tokens) or `json` (legacy whole-file JSON).
  `repairAttempts` (0 or 1, default 1) allows one same-conversation
  repair call after an invalid reply.

## Dependency lock

`requirements.lock` pins the full dependency set (all extras) for
reproducible installs: `pip install -r requirements.lock`. Regenerate
it after changing `pyproject.toml`:

```bash
uv pip compile pyproject.toml --all-extras --python-version 3.12 -o requirements.lock
```

## Python development checks

These are exactly what CI runs (`.github/workflows/ci.yml`):

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,api]"
.\.venv\Scripts\python.exe -m ruff check src tests harness
.\.venv\Scripts\python.exe -m ruff format --check src tests harness
.\.venv\Scripts\python.exe -m mypy src
.\.venv\Scripts\python.exe -m bandit -c .bandit -r src -q
.\.venv\Scripts\python.exe -m pytest -q --cov=asf --cov-report=term-missing
```
