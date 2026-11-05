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

## Module status

| Area | Status | Notes |
| --- | --- | --- |
| Core contracts (`src/asf/contracts/`) | Implemented | JSON Schema + pydantic models kept in lockstep |
| Configuration (`src/asf/configuration/`) | Implemented | Platform + project profiles, `{env: NAME}` secrets only |
| Workflow + state machine (`src/asf/workflow/`, `src/asf/state_machine/`) | Implemented | Pure: no I/O, injected clock/IDs |
| Approval engine (`src/asf/approval/`) | Implemented | Dashboard approvals; Teams adapter exists but is not live-validated |
| Agents (`src/asf/agents/`) | Implemented | All 7 (spec, plan, task, implement, review, test, fix) |
| Orchestrator (`src/asf/orchestrator/`) | Implemented | Transactional tick, code-fix loop, budgets, optimistic locking |
| Model gateways (`src/asf/models/`, `src/asf/integrations/`) | Implemented | Scripted/fake, OpenAI-compatible, Gemini; per-agent routing + usage counting |
| Tools (`src/asf/tools/`) | Implemented | Local repository/sandbox, per-run git worktrees |
| Storage (`src/asf/storage/`) | Implemented | SQLite, MariaDB, in-memory |
| Hosting + CI (`src/asf/integrations/hosting/`) | Implemented | GitHub + GitLab adapters; write paths covered by contract tests, not yet exercised against a live server |
| HTTP API + dashboard (`src/asf/api/`, `apps/dashboard/`) | Implemented | The dashboard's per-project CI badge is still a hardcoded placeholder |
| Evaluation + metrics (`src/asf/evaluation/`, `harness/`) | Implemented | Metrics are in-memory; a persisted metrics table is designed, not built |
| Execution payload splitting | Planned | Large artifact payloads still live in the execution row; the append-only split is designed, not built |

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
