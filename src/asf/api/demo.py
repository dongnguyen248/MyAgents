"""Runnable dashboard-backend demo assembly.

    .venv/bin/python -m asf.api.demo --port 8000        # serve the REST/SSE API
    .venv/bin/python -m asf.api.demo --selftest         # headless end-to-end run

All seven real agents are registered with one deterministic routing
``ScriptedModelGateway``: replies are chosen per agent from the system
prompt and use the exact canned SPEC/PLAN/TASK/CODE/CODE_REVIEW formats the
agents' own tests use. The TestAgent is deterministic: it runs against a
scripted sandbox, except for projects whose profile sets
``repository.path`` — those get the real local workspace adapters
(``asf.tools.local``), so their change sets land in the project folder
and their configured test commands run there for real. This demonstrates
wiring, not real LLM reasoning.
"""

from __future__ import annotations

import argparse
import importlib
import json
import logging
import os
import re
import tempfile
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

import asf
from asf.agents.base import AgentRuntime
from asf.agents.fix.factory import build_fix_agent
from asf.agents.implement.factory import build_implement_agent
from asf.agents.loading import load_plan_template, load_spec_template
from asf.agents.plan.factory import build_plan_agent
from asf.agents.review.factory import build_review_agent
from asf.agents.spec.factory import build_spec_agent
from asf.agents.task.factory import build_task_agent
from asf.agents.test.factory import build_test_agent
from asf.api.app import create_app
from asf.api.decomposer import RequirementDecomposer
from asf.api.hosting_tokens import HostingTokens
from asf.api.model_settings import ModelSettings, SettingsRoutingGateway
from asf.api.service import FactoryService
from asf.approval.models import ApprovalPolicy
from asf.configuration.loader import load_platform_config, load_projects
from asf.configuration.project import ProjectProfile
from asf.configuration.secrets import SecretRef
from asf.configuration.yamlio import scan_secrets
from asf.contracts.models import (
    ActivityEvent,
    AgentMetadata,
    AgentRequest,
    AgentResult,
    ModelRequest,
    ModelResponse,
    ValidationResult,
)
from asf.integrations.hosting.actions import build_hosting_actions
from asf.models.fake import ScriptedModelGateway
from asf.orchestrator import AgentRegistry, Orchestrator
from asf.orchestrator.code_loop import CodeLoopPolicy
from asf.storage.mariadb import MariaDbConfig, MariaDbExecutionStore
from asf.storage.sqlite import SQLiteExecutionStore
from asf.tools.fake import InMemoryRepository, ScriptedSandbox
from asf.tools.local import (
    LocalWorkspace,
    SandboxResourceLimits,
    SandboxSettings,
    WorkspaceRepository,
    WorkspaceSandbox,
)
from asf.workflow.loader import load_workflow

_TASK_REPLY = json.dumps({
    "tasks": [{
        "id": "T1",
        "title": "Create the demo module",
        "milestoneRef": "M1",
        "description": "Implement the demo module described by the SPEC",
        "acceptanceCriteria": ["The demo module exists and imports cleanly"],
        "dependsOn": [],
        "expectedFiles": ["calculator.py"],
        "verificationHint": "Run the project test commands",
    }],
}, indent=2)

_CODE_REPLY = json.dumps({
    "changes": [{
        "path": "calculator.py",
        "operation": "create",
        "content": "def add(a, b):\n    return a + b\n",
    }],
}, indent=2)

_REVIEW_REPLY = '{"findings": [], "verdict": "APPROVE"}'


class DemoRoutingGateway:
    """Deterministic per-agent replies over one ScriptedModelGateway."""

    def __init__(self, templates_dir: Path) -> None:
        self._templates_dir = templates_dir
        self.requests: list[ModelRequest] = []

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        system = request.messages[0].content
        user = request.messages[-1].content
        if "senior business analyst" in system:
            reply = self._spec_reply(user)
        elif "senior software architect" in system:
            reply = self._plan_reply(user)
        elif "breaking down implementation plans" in system:
            reply = _TASK_REPLY
        elif "implementing code changes" in system:
            reply = _CODE_REPLY
        elif "You review exactly one task" in system:
            reply = _REVIEW_REPLY
        elif "You fix one task item" in system:
            reply = _CODE_REPLY
        else:  # pragma: no cover - defensive: every demo agent is routed above
            raise RuntimeError(f"No demo reply routed for system prompt: {system[:60]}")
        return ScriptedModelGateway([reply]).complete(request)

    def _spec_reply(self, user: str) -> str:
        template = load_spec_template(self._templates_dir)
        revised = "## Reviewer feedback" in user
        body = "Revised demo specification." if revised else "Initial demo specification."
        return "# SPEC: Demo\n\n" + "\n\n".join(
            f"{heading}\n{body}" for heading in template.required_sections
        )

    def _plan_reply(self, user: str) -> str:
        template = load_plan_template(self._templates_dir)
        linked = re.search(r"## Linked SPEC\nID: ([^\n]+)\nVersion: ([^\n]+)", user)
        linked_text = (
            f"ID: {linked[1]}\nVersion: {linked[2]}" if linked else "ID: unknown\nVersion: 1"
        )
        sections = {
            "## Linked SPEC": linked_text,
            "## Milestones": (
                "### M1: Demonstrate the approved SPEC handoff\n"
                "- Deliverables: Demo PLAN\n"
                "- Acceptance criteria: PLAN uses the approved SPEC\n"
                "- Depends on: none"
            ),
        }
        return "# PLAN: Demo\n\n" + "\n\n".join(
            f"{heading}\n{sections.get(heading, 'Deterministic demo plan content.')}"
            for heading in template.required_sections
        )


class _FallbackMetrics:
    """Minimal in-memory metrics recorder used until asf.evaluation lands."""

    def __init__(self) -> None:
        self._results: list[AgentResult] = []
        self._events: list[ActivityEvent] = []
        self._decisions: list[dict[str, Any]] = []

    def record(self, agent_id: str, result: AgentResult) -> None:
        self._results.append(result)

    def publish(self, event: ActivityEvent) -> None:
        self._events.append(event)

    def agent_metrics(self, agent_id: str) -> dict[str, Any]:
        own = [result for result in self._results if result.agent_id == agent_id]
        completed = sum(result.status == "SUCCESS" for result in own)
        failed = sum(result.status in ("FAILED", "REJECTED") for result in own)
        cancelled = sum(result.status == "CANCELLED" for result in own)
        total = len(own)
        durations = [result.metrics.duration_seconds for result in own]
        return {
            "total": total, "completed": completed,
            "running": total - completed - failed - cancelled,
            "failed": failed, "cancelled": cancelled,
            "successRate": completed / total if total else 0.0,
            "avgDurationSec": sum(durations) / total if total else 0.0,
            "avgRevisions": 0.0, "humanApprovalRate": 0.0,
            "testPassRate": 0.0, "ciPassRate": 0.0,
        }

    def overview(self) -> dict[str, Any]:
        return {
            "daily": [],
            "human": {
                "approvalRate": 0.0, "rejectionRate": 0.0, "avgRevisions": 0.0,
                "avgApprovalMinutes": 0.0, "daily": [],
            },
            "quality": {
                "codeReviewRejectionRate": 0.0, "testPassRate": 0.0,
                "ciPassRate": 0.0, "reworkRate": 0.0, "daily": [],
            },
            "agents": [],
        }

    def events(self) -> list[ActivityEvent]:
        return list(self._events)

    def project_outcomes(self, project_id: str) -> dict[str, Any]:
        return {}

    def record_approval_decision(self, **kwargs: Any) -> None:
        self._decisions.append(kwargs)


def _skill_body(text: str) -> str:
    """A SKILL.md's instruction body: the text minus YAML frontmatter.

    The frontmatter (name/description) is catalogue metadata for
    humans and tooling; agents consume the body. A file without
    frontmatter is used as-is.
    """
    stripped = text.lstrip()
    if not stripped.startswith("---"):
        return text.strip()
    lines = stripped.splitlines()
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "\n".join(lines[index + 1:]).strip()
    return text.strip()


def _load_metrics() -> Any:
    """Use asf.evaluation's service when importable; otherwise the fallback."""
    for module_name in ("asf.evaluation", "asf.evaluation.service", "asf.evaluation.metrics"):
        try:
            module = importlib.import_module(module_name)
        except Exception:  # nosec B112
            continue
        for class_name in ("MetricsService", "EvaluationService"):
            cls = getattr(module, class_name, None)
            if cls is None:
                continue
            instance = None
            for kwargs in ({"clock": lambda: datetime.now(timezone.utc)}, {}):
                try:
                    instance = cls(**kwargs)
                    break
                except Exception:  # nosec B112
                    continue
            if instance is None:
                continue
            if all(
                hasattr(instance, name)
                for name in ("agent_metrics", "overview", "events", "project_outcomes")
            ):
                return instance
    return _FallbackMetrics()


class DemoFactoryService(FactoryService):
    """FactoryService with demo-scenario defaults for HTTP-started runs.

    The scripted demo has exactly one task item (``T1``) on ref ``main`` and a
    deterministic test command, so a caller that starts a run over HTTP with
    only a requirement still gets a runnable workflow. Caller-supplied inputs
    and context always win; real deployments supply these values from the
    project/task data instead of relying on these defaults.
    """

    _STEP_DEFAULTS: dict[str, dict[str, Any]] = {
        "implement": {"taskItemId": "T1", "ref": "main"},
        "review": {"taskItemId": "T1", "ref": "main"},
        "test": {"taskItemId": "T1", "ref": "main"},
    }

    def __init__(
        self, *args: Any, projects_dir: Path | None = None,
        skills_dir: Path | None = None, **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._projects_dir = projects_dir
        # The skills catalogue lives at the repository root beside
        # projects/ and templates/; tests may point it elsewhere.
        self._skills_dir = (
            skills_dir if skills_dir is not None
            else Path(__file__).resolve().parents[3] / "skills"
        )

    def _project_skills(self, project_id: str) -> list[dict[str, str]]:
        """The project's enabled skills, resolved from the catalogue.

        Each enabled id names a folder in the skills catalogue whose
        SKILL.md (Agent Skills format) is read with its frontmatter
        stripped — the body is what agents consume. A configured
        skill that cannot be read fails the run start loudly, like a
        missing review rules file: silently running without a skill
        the project explicitly enabled would be worse.
        """
        profile = self._project_profiles.get(project_id) or {}
        enabled = profile.get("enabledSkills")
        if not isinstance(enabled, list):
            return []
        resolved: list[dict[str, str]] = []
        for entry in enabled:
            if not isinstance(entry, str) or not entry.strip():
                continue
            skill_id = entry.strip()
            path = self._skills_dir / skill_id / "SKILL.md"
            try:
                text = path.read_text(encoding="utf-8")
            except OSError as error:
                raise ValueError(
                    f"Project '{project_id}' enables skill '{skill_id}'"
                    f" but {path} cannot be read: {error}",
                ) from error
            body = _skill_body(text)
            if body:
                resolved.append({"id": skill_id, "content": body})
        return resolved

    def _default_test_commands(self, project_id: str) -> list[list[str]]:
        """The project's configured test commands, else the demo default.

        A project with a local workspace (``repository.path``) normally
        configures its real test command under
        ``configuration.testCommands`` in its profile; that command then
        runs for real in the project folder via the local sandbox.
        """
        profile = self._project_profiles.get(project_id) or {}
        configuration = profile.get("configuration")
        commands = (
            configuration.get("testCommands")
            if isinstance(configuration, dict) else None
        )
        if (
            isinstance(commands, list) and commands
            and all(
                isinstance(argv, list) and argv
                and all(isinstance(arg, str) and arg for arg in argv)
                for argv in commands
            )
        ):
            return [[str(arg) for arg in argv] for argv in commands]
        return [["python", "-m", "pytest", "-q"]]

    # Shared review standards per language, as ``rules/languages/<pack>.md``
    # under the projects directory. A profile technology token selects the
    # pack(s) the project is reviewed against; frameworks that imply a
    # language (react -> typescript) map to that language's pack.
    _LANGUAGE_PACK_ORDER: tuple[str, ...] = ("java", "typescript", "csharp")
    _TECHNOLOGY_TO_PACK: dict[str, str] = {
        "java": "java",
        "typescript": "typescript",
        "ts": "typescript",
        "react": "typescript",
        "csharp": "csharp",
        "c#": "csharp",
        "dotnet": "csharp",
        ".net": "csharp",
    }

    def _language_rule_packs(self, project_id: str) -> list[str]:
        """Shared language rule packs selected by the project's stack."""
        if self._projects_dir is None:
            return []
        view = self._projects.get(project_id) or {}
        technologies = view.get("technologies")
        if not isinstance(technologies, list):
            return []
        selected = {
            self._TECHNOLOGY_TO_PACK[token.strip().lower()]
            for token in technologies
            if isinstance(token, str)
            and token.strip().lower() in self._TECHNOLOGY_TO_PACK
        }
        packs: list[str] = []
        for pack in self._LANGUAGE_PACK_ORDER:
            if pack not in selected:
                continue
            path = self._projects_dir / "rules" / "languages" / f"{pack}.md"
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue  # A missing shared pack must not block other runs.
            if text.strip():
                packs.append(text.strip())
        return packs

    def _review_rules(self, project_id: str) -> str:
        """The project's review standards, as one text block.

        Shared language packs (``rules/languages/``, selected by the
        profile's technologies) come first, then the project's own rules:
        ``configuration.review.rulesFiles`` lists Markdown rule files
        relative to the projects directory and ``configuration.review.
        rules`` holds inline rule text; files are concatenated in listed
        order, inline text last. A configured project file that cannot be
        read fails the run start loudly — silently reviewing without the
        project's rules would be worse than not starting at all.
        """
        parts: list[str] = self._language_rule_packs(project_id)
        profile = self._project_profiles.get(project_id) or {}
        configuration = profile.get("configuration")
        review = (
            configuration.get("review") if isinstance(configuration, dict)
            else None
        )
        if not isinstance(review, dict):
            return "\n\n".join(parts)
        files = review.get("rulesFiles")
        if isinstance(files, list):
            for entry in files:
                if not isinstance(entry, str) or not entry.strip():
                    continue
                if self._projects_dir is None:
                    raise ValueError(
                        f"Project '{project_id}' configures review rulesFiles"
                        " but the service has no projects directory",
                    )
                path = (self._projects_dir / entry).resolve()
                if not path.is_relative_to(self._projects_dir.resolve()):
                    raise ValueError(
                        f"Review rules file '{entry}' for project"
                        f" '{project_id}' escapes the projects directory",
                    )
                try:
                    text = path.read_text(encoding="utf-8")
                except OSError as error:
                    raise ValueError(
                        f"Review rules file '{entry}' for project"
                        f" '{project_id}' cannot be read: {error}",
                    ) from error
                if text.strip():
                    parts.append(text.strip())
        inline = review.get("rules")
        if isinstance(inline, str) and inline.strip():
            parts.append(inline.strip())
        return "\n\n".join(parts)

    def start_run(
        self,
        task_id: str,
        project_id: str,
        inputs: Any = None,
        context: Any = None,
    ) -> Any:
        merged_inputs: dict[str, Any] = {
            step: dict(values) for step, values in self._STEP_DEFAULTS.items()
        }
        for step, values in dict(inputs or {}).items():
            merged_inputs[step] = {**merged_inputs.get(step, {}), **dict(values)}
        merged_context: dict[str, Any] = {
            "project": {"testCommands": self._default_test_commands(project_id)},
        }
        review_rules = self._review_rules(project_id)
        if review_rules:
            merged_context["project"]["reviewRules"] = review_rules
        skills = self._project_skills(project_id)
        if skills:
            merged_context["project"]["skills"] = skills
            merged_context["project"]["enabledSkills"] = [
                skill["id"] for skill in skills
            ]
        for key, value in dict(context or {}).items():
            if key == "project" and isinstance(value, dict):
                merged_context["project"] = {**merged_context["project"], **value}
            else:
                merged_context[key] = value
        return super().start_run(
            task_id, project_id, inputs=merged_inputs, context=merged_context,
        )


def _project_writer(
    projects_dir: Path, *, overwrite: bool = False,
) -> Callable[[ProjectProfile], None]:
    """Persist dashboard-managed projects as ``projects/<id>.yaml``.

    The written file is a regular project profile: it goes through the same
    secret scan as hand-written files (literal secrets are rejected; use
    ``{env: VAR}`` references), and the loader picks it up on the next start
    because its stem equals the profile id. ``overwrite`` is for edits of an
    existing project; creation refuses to clobber a file.
    """

    def write(profile: ProjectProfile) -> None:
        data = profile.to_contract()
        if scan_secrets(data):
            raise ValueError(
                "Project profile contains literal secrets; "
                "use {env: VAR} references instead",
            )
        path = projects_dir / f"{profile.id}.yaml"
        if path.exists() and not overwrite:
            raise ValueError(f"Project file already exists: {path.name}")
        path.write_text(
            yaml.safe_dump(data, sort_keys=False), encoding="utf-8",
        )

    return write


def _project_remover(projects_dir: Path) -> Callable[[str], None]:
    """Delete ``projects/<id>.yaml`` for a dashboard-deleted project."""

    def remove(project_id: str) -> None:
        (projects_dir / f"{project_id}.yaml").unlink(missing_ok=True)

    return remove


class _WorkspaceBindingAgent:
    """Agent wrapper that binds the local workspace to the run's project.

    The repository/sandbox ports carry no project id, so before the code
    agents (implement, test, fix) execute, the workspace is bound to the
    request's project; the routed ports then resolve that project's
    ``repository.path`` folder, if it has one. Runs are driven one step
    at a time by the local worker, so the binding is never contended.
    """

    def __init__(self, inner: Any, workspace: LocalWorkspace) -> None:
        self._inner = inner
        self._workspace = workspace

    def get_metadata(self) -> AgentMetadata:
        return self._inner.get_metadata()

    def validate(self, request: AgentRequest) -> ValidationResult:
        return self._inner.validate(request)

    def execute(self, request: AgentRequest) -> AgentResult:
        self._workspace.bind(request.project_id)
        return self._inner.execute(request)


def _profile_root(profile: ProjectProfile) -> str | None:
    path = profile.repository.get("path")
    return path if isinstance(path, str) and path.strip() else None


def _profile_sandbox_settings(profile: ProjectProfile) -> SandboxSettings | None:
    """Extracts a local project's sandbox settings from its profile.

    Reads ``configuration.testEnv`` (literal strings or
    ``{"env": NAME}`` references, resolved against the process
    environment — a missing reference fails loudly, the platform's
    secret convention), ``configuration.testEnvAllowlist`` and
    ``configuration.sandboxLimits``. Returns None when the profile
    declares none of them.
    """
    configuration = profile.configuration
    raw_env = configuration.get("testEnv")
    raw_allowlist = configuration.get("testEnvAllowlist")
    raw_limits = configuration.get("sandboxLimits")
    if raw_env is None and raw_allowlist is None and raw_limits is None:
        return None
    extra: dict[str, str] = {}
    if raw_env is not None:
        if not isinstance(raw_env, dict):
            raise ValueError(
                f"Project {profile.id}: configuration.testEnv must be a map",
            )
        for name, value in raw_env.items():
            if isinstance(value, dict) and set(value) == {"env"}:
                extra[str(name)] = SecretRef(env=str(value["env"])).resolve()
            elif isinstance(value, str):
                extra[str(name)] = value
            else:
                raise ValueError(
                    f"Project {profile.id}: configuration.testEnv.{name} must"
                    " be a string or an {env: NAME} reference",
                )
    allowlist: tuple[str, ...] = ()
    if raw_allowlist is not None:
        if not isinstance(raw_allowlist, list) or not all(
            isinstance(name, str) for name in raw_allowlist
        ):
            raise ValueError(
                f"Project {profile.id}: configuration.testEnvAllowlist must"
                " be a list of variable names",
            )
        allowlist = tuple(raw_allowlist)
    limits: SandboxResourceLimits | None = None
    if raw_limits is not None:
        if not isinstance(raw_limits, dict):
            raise ValueError(
                f"Project {profile.id}: configuration.sandboxLimits must be a map",
            )

        def _limit(key: str) -> int | None:
            value = raw_limits.get(key)
            if value is None:
                return None
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(
                    f"Project {profile.id}: configuration.sandboxLimits.{key}"
                    " must be a positive integer",
                )
            return value

        limits = SandboxResourceLimits(
            cpu_seconds=_limit("cpuSeconds"),
            memory_bytes=_limit("memoryBytes"),
            max_processes=_limit("maxProcesses"),
        )
    return SandboxSettings(
        env_allowlist=allowlist, env_extra=extra, resource_limits=limits,
    )


def build_demo(
    db_path: Path,
    *,
    store: SQLiteExecutionStore | MariaDbExecutionStore | None = None,
) -> tuple[FactoryService, Orchestrator, Any]:
    """Assemble store, engine (all seven agents), and dashboard service.

    ``db_path`` locates the SQLite store and the model-settings file kept
    beside it; pass ``store`` to run on a different execution store (e.g.
    MariaDB) — ``db_path`` then only anchors the settings file.
    """
    root = Path(asf.__file__).resolve().parents[2]
    templates_dir = root / "templates"
    platform = load_platform_config(root / "config")
    projects_dir = root / "projects"
    projects = load_projects(projects_dir)
    definition = load_workflow(root / "workflows" / "software-development.yaml")

    def clock() -> datetime:
        return datetime.now(timezone.utc)

    def new_id() -> str:
        return str(uuid4())

    # UI-managed model provider settings: beside the run DB by default,
    # so a provider/key configured in the dashboard survives restarts.
    settings_override = os.environ.get("ASF_MODEL_SETTINGS_FILE")
    settings_path = (
        Path(settings_override) if settings_override
        else db_path.parent / "model-settings.json"
    )
    model_settings = ModelSettings(settings_path)
    # Per-project hosting tokens entered in the dashboard, kept beside
    # the run DB like the model settings — never in the project YAML.
    tokens_override = os.environ.get("ASF_HOSTING_TOKENS_FILE")
    hosting_tokens = HostingTokens(
        Path(tokens_override) if tokens_override
        else db_path.parent / "hosting-tokens.json",
    )
    runtime = AgentRuntime(
        models=SettingsRoutingGateway(
            model_settings, DemoRoutingGateway(templates_dir),
        ),
        clock=clock, new_id=new_id,
    )
    # Local workspace: projects whose profile carries repository.path get
    # real filesystem repository/sandbox adapters (agents read the actual
    # files, change sets land in the folder, test commands really run);
    # every other project keeps the in-memory/scripted fakes.
    workspace = LocalWorkspace(
        {
            profile.id: root_path
            for profile in projects.values()
            if (root_path := _profile_root(profile)) is not None
        },
        sandbox_settings={
            profile.id: settings
            for profile in projects.values()
            if (settings := _profile_sandbox_settings(profile)) is not None
        },
    )
    repository = WorkspaceRepository(workspace, InMemoryRepository())
    sandbox = WorkspaceSandbox(workspace, ScriptedSandbox())
    registry = AgentRegistry()
    registry.register(build_spec_agent(runtime, platform, templates_dir))
    registry.register(build_plan_agent(runtime, platform, templates_dir))
    registry.register(build_task_agent(runtime, platform, templates_dir))
    registry.register(_WorkspaceBindingAgent(
        build_implement_agent(runtime, platform, templates_dir, repository),
        workspace,
    ))
    registry.register(build_review_agent(runtime, platform, templates_dir))
    registry.register(_WorkspaceBindingAgent(
        build_test_agent(runtime, platform, templates_dir, sandbox),
        workspace,
    ))
    registry.register(_WorkspaceBindingAgent(
        build_fix_agent(runtime, platform, templates_dir, repository),
        workspace,
    ))

    store = store if store is not None else SQLiteExecutionStore(db_path)
    metrics = _load_metrics()
    # Hosting actions (Phase 8): projects whose profile links a GitLab /
    # GitHub repository (repository.url + provider, token from the
    # environment) get real push / change-request / pipeline behavior at
    # the CI and merge steps; other projects keep the no-op success.
    # Profiles are read through the service, which only exists after the
    # engine — the actions run on ticks, long after this assembly, so a
    # late-bound lookup is safe.
    service_ref: dict[str, FactoryService] = {}

    def profile_of(project_id: str) -> Mapping[str, Any] | None:
        service = service_ref.get("service")
        return service._project_profiles.get(project_id) if service else None

    engine = Orchestrator(
        definition, registry, clock=clock, new_id=new_id, store=store,
        approval_policy=ApprovalPolicy(reviewers=["dashboard"]),
        # Bounded rework: a CHANGES_REQUESTED review or a FAIL test verdict
        # routes the CODE (with the review / test report attached) to the
        # Fix agent and re-runs review + test, up to 3 fixes per task item;
        # beyond that the run escalates for a human instead of dying at the
        # quality gate. Without this policy the engine stops the run on the
        # first failing verdict.
        code_loop=CodeLoopPolicy(max_fixes=3),
        actions=build_hosting_actions(
            profiles=profile_of, clock=clock, tokens=hosting_tokens.get,
        ),
        events=metrics if hasattr(metrics, "publish") else None,
        metrics=metrics if hasattr(metrics, "record") else None,
    )
    def on_created(profile: ProjectProfile) -> None:
        _project_writer(projects_dir)(profile)
        workspace.set_root(profile.id, _profile_root(profile))
        workspace.set_sandbox_settings(
            profile.id, _profile_sandbox_settings(profile),
        )

    def on_updated(profile: ProjectProfile) -> None:
        _project_writer(projects_dir, overwrite=True)(profile)
        workspace.set_root(profile.id, _profile_root(profile))
        workspace.set_sandbox_settings(
            profile.id, _profile_sandbox_settings(profile),
        )

    def on_deleted(project_id: str) -> None:
        _project_remover(projects_dir)(project_id)
        workspace.remove(project_id)

    service = DemoFactoryService(
        engine, projects=projects, metrics=metrics, store=store,
        reviewer="dashboard", clock=clock, projects_dir=projects_dir,
        on_project_created=on_created,
        on_project_updated=on_updated,
        on_project_deleted=on_deleted,
        model_settings=model_settings,
        hosting_tokens=hosting_tokens,
        # Auto-splitting runs on the same routed gateway as the
        # agents, so it uses the configured provider and shared
        # model; with the scripted provider its JSON validation
        # fails and the service falls back to running the task
        # whole (the failure is shown on the run).
        decomposer=RequirementDecomposer(runtime.models),
    )
    service_ref["service"] = service
    return service, engine, store


def run_selftest(service: FactoryService, engine: Orchestrator) -> int:
    """Drive one run to completion, approving every artifact as 'dashboard'."""
    project_id = service.list_projects()[0]["id"]
    run = service.start_run(
        "demo-task", project_id,
        inputs={
            "spec": {"requirement": "Demonstrate the dashboard backend end to end"},
            "implement": {"taskItemId": "T1", "ref": "main"},
            "review": {"taskItemId": "T1", "ref": "main"},
            "test": {"taskItemId": "T1", "ref": "main"},
        },
        context={"project": {"testCommands": [["python", "-m", "pytest", "-q"]]}},
    )
    for _ in range(100):
        run = engine.get(run.id)
        print(f"stage: {run.state.stage}")
        if run.state.stage in ("COMPLETED", "FAILED", "CANCELLED"):
            break
        if run.approval_id is not None:
            pending = engine.pending_approval(run.id)
            service.decide_approval(pending.id, decision="APPROVE")
        else:
            service.tick_run(run.id)
    service.wait_for_drives()
    run = engine.get(run.id)
    artifact_types = {artifact.type for artifact in run.artifact_history.values()}
    missing = {"SPEC", "PLAN", "TASK", "CODE"} - artifact_types
    if run.state.stage != "COMPLETED" or missing:
        print(f"SELFTEST FAILED: stage={run.state.stage} missing={sorted(missing)}")
        for error in run.errors:
            print(f"error: {error.code}: {error.message}")
        return 1
    print(f"SELFTEST OK - final stage: {run.state.stage}")
    return 0


def _resolve_db_path(db_arg: Path | None, *, selftest: bool) -> Path:
    """Where the demo's SQLite store lives.

    An explicit ``--db`` wins. Serving defaults to ``<repo>/data/asf.sqlite``
    so runs — and the model settings stored beside the DB — survive
    restarts no matter which directory the backend is started from; the
    previous default (a fresh temp directory per start) silently discarded
    every run on restart. The headless selftest keeps a throwaway temp DB
    so it never pollutes the real one.
    """
    if db_arg is not None:
        return db_arg
    if selftest:
        return Path(tempfile.mkdtemp(prefix="asf-api-demo-")) / "demo.sqlite"
    root = Path(asf.__file__).resolve().parents[2]
    return root / "data" / "asf.sqlite"


def _load_dotenv(path: Path) -> bool:
    """Load ``KEY=VALUE`` pairs from a repo-root ``.env`` into the environment.

    Real environment variables win — the file is a local-development
    convenience so settings like ``ASF_MARIADB_PASSWORD`` do not have to be
    re-typed every run. ``.env`` is git-ignored (see ``.env.example`` for
    the supported keys); it must never be committed.
    """
    if not path.is_file():
        return False
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)
    return True


def configure_logging() -> None:
    """Send ASF's own log lines to this process's console.

    Agent failures and provider errors otherwise surface only as a
    one-line dashboard banner; the recorded causes (which model was
    sent, why a reply was rejected) are logged under the ``asf``
    namespace and would go nowhere without a handler. Idempotent.
    Level from ASF_LOG_LEVEL (default INFO).
    """
    logger = logging.getLogger("asf")
    if getattr(logger, "_asf_console_configured", False):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    logger.addHandler(handler)
    logger.setLevel(os.environ.get("ASF_LOG_LEVEL", "INFO").upper())
    logger.propagate = False
    logger._asf_console_configured = True  # type: ignore[attr-defined]


def main() -> None:
    configure_logging()
    dotenv_path = Path(asf.__file__).resolve().parents[2] / ".env"
    if _load_dotenv(dotenv_path):
        print(f"Loaded environment from {dotenv_path}")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--db", type=Path, default=None, help="SQLite store path")
    parser.add_argument(
        "--mariadb", action="store_true",
        help="Store runs in MariaDB (ASF_MARIADB_* env vars) instead of SQLite",
    )
    parser.add_argument(
        "--selftest", action="store_true",
        help="Run one headless end-to-end run instead of serving HTTP",
    )
    args = parser.parse_args()
    if args.mariadb:
        config = MariaDbConfig.from_env()
        maria_store = MariaDbExecutionStore(config)
        # Runs live in MariaDB; the model-settings file still needs a home,
        # so anchor it at the usual data directory.
        service, engine, store = build_demo(
            _resolve_db_path(None, selftest=False), store=maria_store,
        )
        db_label = (
            f"mariadb {config.user}@{config.host}:{config.port}/{config.database}"
        )
    else:
        db_path = _resolve_db_path(args.db, selftest=args.selftest)
        service, engine, store = build_demo(db_path)
        db_label = str(db_path.resolve())
    try:
        if args.selftest:
            raise SystemExit(run_selftest(service, engine))
        import uvicorn

        # Runs left mid-flight by a previous backend process (restart,
        # crash) pick themselves up to their next approval gate.
        service.drive_active_runs()
        print(f"Dashboard API on http://127.0.0.1:{args.port} (db: {db_label})")
        print("Dashboard: set VITE_API_BASE_URL to that URL and run the frontend dev server.")
        # Bound the graceful shutdown: the dashboard holds a server-sent
        # events stream open for as long as its tab lives, and uvicorn
        # otherwise waits for it forever on Ctrl+C ("Waiting for
        # connections to close"). Five seconds of grace, then the
        # remaining connections close and the process exits; run state
        # lives in the store and mid-flight runs heal on the next boot.
        uvicorn.run(
            create_app(service), host="127.0.0.1", port=args.port,
            timeout_graceful_shutdown=5,
        )
    finally:
        store.close()


if __name__ == "__main__":
    main()
