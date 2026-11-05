"""Framework-free dashboard service over the orchestrator.

``FactoryService`` maps the orchestrator's contract-shaped views onto the
exact JSON shapes the dashboard frontend consumes (see
``apps/dashboard/src/types/*.ts``). It contains no web-framework imports so it
can be unit-tested (and reused) without FastAPI installed.

Lossy points of the mapping are documented in ``src/asf/api/README.md``.
Time is never read from the system clock here: timestamps come from the
runs themselves or from the injected ``clock`` callable.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from pydantic import ValidationError

from asf.approval.errors import ApprovalError
from asf.configuration.project import ProjectProfile
from asf.configuration.yamlio import deep_merge
from asf.contracts.models import ActivityEvent
from asf.orchestrator.code_loop import FIX_STAGE
from asf.orchestrator.engine import Orchestrator
from asf.orchestrator.execution import WorkflowExecution
from asf.state_machine.graph import build_graph
from asf.state_machine.status import kind_of
from asf.workflow.definition import WorkflowDefinition, WorkflowStepDef


class MetricsProtocol(Protocol):
    """The fixed evaluation interface the service programs against.

    Implementations are supplied by the assembly (``asf.evaluation`` or a
    test fake); this module deliberately does not import that package.
    """

    def agent_metrics(self, agent_id: str) -> dict[str, Any]: ...

    def overview(self) -> dict[str, Any]: ...

    def events(self) -> list[ActivityEvent]: ...

    def project_outcomes(self, project_id: str) -> dict[str, Any]: ...


class ProjectExistsError(Exception):
    """Raised when creating a project whose id is already registered."""


class ProjectNotFoundError(Exception):
    """Raised when updating or deleting an unknown project id."""


class ProjectConflictError(Exception):
    """Raised when a project cannot change state, e.g. delete with active runs."""


_PROJECT_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]*")

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

_AGENT_STATUS_MAP = {
    "RUNNING": "BUSY",
    "IDLE": "IDLE",
    "WAITING": "WAITING",
    "ERROR": "ERROR",
    "DISABLED": "DISABLED",
    "OFFLINE": "OFFLINE",
}

_RESULT_STATUS_MAP = {
    "SUCCESS": "Completed",
    "FAILED": "Failed",
    "REJECTED": "Failed",
    "CANCELLED": "Cancelled",
    "WAITING": "Running",
}

_TASK_STATUSES = {
    "NEW",
    "SPEC_DRAFT", "SPEC_REVIEW", "SPEC_REJECTED", "SPEC_APPROVED",
    "PLAN_DRAFT", "PLAN_REVIEW", "PLAN_REJECTED", "PLAN_APPROVED",
    "TASK_DRAFT", "TASK_REVIEW", "TASK_REJECTED", "TASK_APPROVED",
    "IMPLEMENTING", "CODE_REVIEW", "TESTING", "CI", "READY_TO_MERGE",
    "COMPLETED", "FAILED", "CANCELLED",
}

_WORKFLOW_TYPES = {"feature-development", "bug-fix", "refactoring"}
_PRIORITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
_APPROVAL_TYPES = {"SPEC", "PLAN", "TASK", "CODE_REVIEW", "DEPLOYMENT"}
_TERMINAL_STAGES = {"COMPLETED", "FAILED", "CANCELLED"}

_DASHBOARD_STEP_IDS = {"spec", "plan", "task", "implementation", "code_review",
                       "testing", "ci", "merge"}
_STEP_ID_BY_STEP_ID = {
    "spec": "spec", "plan": "plan", "task": "task", "implement": "implementation",
    "review": "code_review", "test": "testing", "ci": "ci", "merge": "merge",
}
_STEP_ID_BY_STAGE = {
    "SPEC": "spec", "PLAN": "plan", "TASK": "task", "IMPLEMENTING": "implementation",
    "CODE_REVIEW": "code_review", "TESTING": "testing", "CI": "ci",
    "READY_TO_MERGE": "merge",
}
_APPROVAL_STEP_IDS = {"spec": "spec_approval", "plan": "plan_approval", "task": "task_approval"}

_ZERO_AGENT_METRICS: dict[str, Any] = {
    "total": 0, "completed": 0, "running": 0, "failed": 0, "cancelled": 0,
    "successRate": 0.0, "avgDurationSec": 0.0, "avgRevisions": 0.0,
    "humanApprovalRate": 0.0, "testPassRate": 0.0, "ciPassRate": 0.0,
}

_EMPTY_OVERVIEW: dict[str, Any] = {
    "daily": [],
    "human": {
        "approvalRate": 0.0, "rejectionRate": 0.0, "avgRevisions": 0.0,
        "avgApprovalMinutes": 0.0, "daily": [],
    },
    "quality": {
        "codeReviewRejectionRate": 0.0, "testPassRate": 0.0, "ciPassRate": 0.0,
        "reworkRate": 0.0, "daily": [],
    },
    "agents": [],
}

# Dashboard decision kind -> (engine decision, dashboard approval status)
_DECISIONS = {
    "APPROVE": ("APPROVED", "APPROVED"),
    "REJECT": ("REJECTED", "REJECTED"),
    "REQUEST_CHANGES": ("REQUEST_CHANGES", "CHANGES_REQUESTED"),
}


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _valid_test_commands(raw: Any) -> list[list[str]]:
    """Normalize a profile's ``configuration.testCommands`` value.

    Returns the commands as a list of argv lists, or an empty list when
    the value is not a non-empty list of non-empty string lists (the
    test agent reports malformed commands itself when a run uses them;
    the view layer just refuses to echo nonsense).
    """
    if not isinstance(raw, list) or not raw:
        return []
    commands: list[list[str]] = []
    for argv in raw:
        if (
            not isinstance(argv, list) or not argv
            or not all(isinstance(arg, str) and arg for arg in argv)
        ):
            return []
        commands.append([str(arg) for arg in argv])
    return commands


def _camelize(key: str) -> str:
    head, _, rest = key.partition("_")
    while rest:
        nxt, _, rest = rest.partition("_")
        head += nxt[:1].upper() + nxt[1:]
    return head


class FactoryService:
    """Dashboard-shaped read/write views over one ``Orchestrator`` instance."""

    def __init__(
        self,
        engine: Orchestrator,
        *,
        projects: Mapping[str, Any],
        metrics: MetricsProtocol | None = None,
        store: Any = None,
        reviewer: str = "dashboard",
        clock: Callable[[], datetime] | None = None,
        on_project_created: Callable[[ProjectProfile], None] | None = None,
        on_project_updated: Callable[[ProjectProfile], None] | None = None,
        on_project_deleted: Callable[[str], None] | None = None,
        model_settings: Any = None,
    ) -> None:
        self._engine = engine
        self._metrics = metrics
        self._store = store
        self._reviewer = reviewer
        self._on_project_created = on_project_created
        self._on_project_updated = on_project_updated
        self._on_project_deleted = on_project_deleted
        self._model_settings = model_settings
        # Raw profile payloads, kept so updates can merge over them and
        # preserve fields the caller did not resend (e.g. repository.url or
        # approval reviewers added by hand in the profile file).
        self._project_profiles: dict[str, dict[str, Any]] = {}
        for pid, profile in projects.items():
            if isinstance(profile, ProjectProfile):
                self._project_profiles[pid] = profile.to_contract()
            elif isinstance(profile, Mapping):
                self._project_profiles[pid] = dict(profile)
        # The assembly injects a clock; the engine's own clock is the fallback
        # so this service still never reads the system clock directly.
        self._clock = clock or getattr(engine, "_clock", None)
        self._projects = {
            pid: self._normalize_project(pid, profile) for pid, profile in projects.items()
        }
        self._tracked: list[str] = []
        self._store_runs: dict[str, WorkflowExecution] = {}
        # Background drive threads, by run id (see _drive_in_background).
        self._drive_lock = threading.Lock()
        self._drive_threads: dict[str, threading.Thread] = {}
        # Cooperative cancellation: runs whose drive thread is mid-dispatch
        # cannot be cancelled synchronously (the engine refuses to mutate a
        # run while a step is in flight), so a cancel request is recorded
        # here and the drive itself applies it between steps.
        self._cancel_requested: set[str] = set()

    # ------------------------------------------------------------------
    # model provider settings (optional; injected by the assembly)
    # ------------------------------------------------------------------
    def get_model_settings(self) -> dict[str, Any] | None:
        """Public model settings (never contains the API key)."""
        if self._model_settings is None:
            return None
        return self._model_settings.public()

    def update_model_settings(
        self, payload: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        if self._model_settings is None:
            return None
        return self._model_settings.update(payload)

    def test_model_settings(
        self, agent: str | None = None,
    ) -> dict[str, Any] | None:
        if self._model_settings is None:
            return None
        return self._model_settings.test(agent=agent)

    # ------------------------------------------------------------------
    # project normalization
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_project(project_id: str, profile: Any) -> dict[str, Any]:
        if isinstance(profile, ProjectProfile):
            technologies: list[str] = []
            groups: dict[str, list[str]] = {}
            for group, values in profile.technology.items():
                items = values if isinstance(values, list) else [values]
                groups[str(group)] = [item for item in items if isinstance(item, str)]
                for value in items:
                    if isinstance(value, str) and value not in technologies:
                        technologies.append(value)
            approval = profile.configuration.get("approval")
            channel = (
                approval.get("channel") if isinstance(approval, Mapping) else None
            )
            return {
                "id": profile.id,
                "name": profile.name,
                "repositoryProvider": str(profile.repository.get("provider", "")),
                "repositoryUrl": str(profile.repository.get("url") or ""),
                "repositoryPath": str(profile.repository.get("path") or ""),
                "testCommands": _valid_test_commands(
                    profile.configuration.get("testCommands"),
                ),
                "technologies": technologies,
                "description": profile.description,
                "workflow": profile.workflow,
                "enabledSkills": [str(skill) for skill in profile.enabled_skills],
                "technologyGroups": groups,
                "approvalChannel": channel if isinstance(channel, str) else "",
            }
        data = dict(profile)
        repository = data.get("repository") or {}
        provider = data.get("repositoryProvider") or repository.get("provider", "")
        raw_technologies = data.get("technologies")
        technologies = (
            [value for value in raw_technologies if isinstance(value, str)]
            if isinstance(raw_technologies, list)
            else []
        )
        if not isinstance(raw_technologies, list):
            technology = data.get("technology") or {}
            if isinstance(technology, Mapping):
                for values in technology.values():
                    for value in values if isinstance(values, list) else [values]:
                        if isinstance(value, str) and value not in technologies:
                            technologies.append(value)
        technology_map = data.get("technology") or {}
        groups = {}
        if isinstance(technology_map, Mapping):
            for group, values in technology_map.items():
                items = values if isinstance(values, list) else [values]
                groups[str(group)] = [str(item) for item in items if isinstance(item, str)]
        configuration = data.get("configuration") or {}
        approval = (
            configuration.get("approval") if isinstance(configuration, Mapping) else None
        )
        channel = approval.get("channel") if isinstance(approval, Mapping) else None
        raw_skills = data.get("enabledSkills", data.get("enabled_skills"))
        return {
            "id": str(data.get("id", project_id)),
            "name": str(data.get("name", project_id)),
            "repositoryProvider": str(provider),
            "repositoryUrl": (
                str(repository.get("url") or "")
                if isinstance(repository, Mapping) else ""
            ),
            "repositoryPath": (
                str(repository.get("path") or "")
                if isinstance(repository, Mapping) else ""
            ),
            "testCommands": _valid_test_commands(
                configuration.get("testCommands")
                if isinstance(configuration, Mapping) else None
            ),
            "technologies": [str(item) for item in technologies],
            "description": str(data.get("description", "")),
            "workflow": str(data.get("workflow", "")),
            "enabledSkills": (
                [str(skill) for skill in raw_skills if isinstance(skill, str)]
                if isinstance(raw_skills, list) else []
            ),
            "technologyGroups": groups,
            "approvalChannel": channel if isinstance(channel, str) else "",
        }

    # ------------------------------------------------------------------
    # run discovery
    # ------------------------------------------------------------------
    def track(self, run_id: str) -> WorkflowExecution | None:
        """Register an externally started run so it appears in the views."""
        if run_id not in self._tracked:
            self._tracked.append(run_id)
        try:
            return self._engine.get(run_id)
        except Exception:
            return self._store_runs.get(run_id)

    def _discover_store_runs(self) -> None:
        if self._store is None:
            return
        for project_id in self._projects:
            try:
                executions = self._store.list_executions(project_id)
            except Exception:  # nosec B112
                continue
            for run in executions:
                self._store_runs[run.id] = run
                if run.id not in self._tracked:
                    self._tracked.append(run.id)

    def _runs(self) -> list[WorkflowExecution]:
        self._discover_store_runs()
        found: dict[str, WorkflowExecution] = {}
        for run_id in self._tracked:
            try:
                found[run_id] = self._engine.get(run_id)
            except Exception:
                if run_id in self._store_runs:
                    found[run_id] = self._store_runs[run_id]
        for run_id, run in self._store_runs.items():
            found.setdefault(run_id, run)
        return sorted(found.values(), key=lambda run: (run.started_at, run.id))

    # ------------------------------------------------------------------
    # engine internals: registry / definition / stage helpers
    # ------------------------------------------------------------------
    def _metadata_list(self) -> list[Any]:
        registry = getattr(self._engine, "_registry", None)
        return list(registry.list()) if registry is not None else []

    def _metadata(self, agent_id: str) -> Any | None:
        return next((m for m in self._metadata_list() if m.id == agent_id), None)

    def _definition(self, run: WorkflowExecution | None = None) -> WorkflowDefinition | None:
        definition = getattr(self._engine, "_definition", None)
        if isinstance(definition, WorkflowDefinition):
            return definition
        if run is not None and run.definition:
            try:
                return WorkflowDefinition.model_validate(run.definition)
            except Exception:
                return None
        return None

    def _step_for_stage(
        self, run: WorkflowExecution, stage: str,
    ) -> WorkflowStepDef | None:
        definition = self._definition(run)
        if definition is None:
            return None
        for step in definition.steps:
            if stage in step.generated_stages():
                return step
        return None

    def _agent_id_for_type(self, agent_type: str | None) -> str | None:
        if agent_type is None:
            return None
        metadata = next((m for m in self._metadata_list() if m.type == agent_type), None)
        return metadata.id if metadata else None

    def _agent_type_for_id(self, agent_id: str | None) -> str | None:
        if agent_id is None:
            return None
        metadata = self._metadata(agent_id)
        return metadata.type if metadata else None

    def _stage_kind(self, run: WorkflowExecution, stage: str) -> str | None:
        definition = self._definition(run)
        if definition is None:
            return None
        try:
            return str(kind_of(build_graph(definition), stage))
        except Exception:
            return None

    def _now(self) -> datetime | None:
        return self._clock() if self._clock is not None else None

    # ------------------------------------------------------------------
    # agents
    # ------------------------------------------------------------------
    def _agent_metrics(self, agent_id: str) -> dict[str, Any]:
        raw: Any = None
        if self._metrics is not None and hasattr(self._metrics, "agent_metrics"):
            try:
                raw = self._metrics.agent_metrics(agent_id)
            except Exception:
                raw = None
        if not isinstance(raw, Mapping):
            return dict(_ZERO_AGENT_METRICS)
        view = dict(_ZERO_AGENT_METRICS)
        for key, value in raw.items():
            camel = _camelize(str(key))
            if camel in view:
                view[camel] = value
        if "healthScore" in raw:
            view["healthScore"] = raw["healthScore"]
        return view

    def _agent_view(self, metadata: Any) -> dict[str, Any]:
        config = metadata.configuration or {}
        runs = self._runs()
        own = [
            (run, result) for run in runs for result in run.results
            if result.agent_id == metadata.id
        ]
        last_activity = max((run.updated_at for run, _ in own), default=None)
        current: WorkflowExecution | None = None
        for run in runs:
            if run.state.stage in _TERMINAL_STAGES:
                continue
            step = self._step_for_stage(run, run.state.stage)
            if step is not None and step.agent_type == metadata.type:
                current = run
                break
        status = _AGENT_STATUS_MAP.get(str(metadata.status), "OFFLINE")
        if current is not None and status == "IDLE":
            status = "BUSY"
        view: dict[str, Any] = {
            "id": metadata.id,
            "name": metadata.name,
            "type": metadata.type,
            "status": status,
            "version": metadata.version,
            "model": str(config.get("model") or config.get("modelProfile") or "default"),
            "lastActivityAt": _iso(last_activity or self._now() or _EPOCH),
            "metrics": self._agent_metrics(metadata.id),
        }
        if current is not None:
            view["currentTaskId"] = current.task_id
            view["currentTaskTitle"] = self._task_title(current)
            view["currentProjectId"] = current.project_id
            view["startedAt"] = _iso(current.started_at)
        return view

    def list_agents(self) -> list[dict[str, Any]]:
        return [self._agent_view(metadata) for metadata in self._metadata_list()]

    def get_agent(self, agent_id: str) -> dict[str, Any] | None:
        metadata = self._metadata(agent_id)
        return self._agent_view(metadata) if metadata is not None else None

    def get_agent_config(self, agent_id: str) -> dict[str, Any] | None:
        metadata = self._metadata(agent_id)
        if metadata is None:
            return None
        config = metadata.configuration or {}
        agent = self._agent_view(metadata)
        retry = config.get("retryPolicy") or {}
        if not isinstance(retry, Mapping):
            retry = {}
        return {
            "agentId": metadata.id,
            "name": metadata.name,
            "type": metadata.type,
            "enabled": str(metadata.status) != "DISABLED",
            "model": agent["model"],
            "modelVersion": str(config.get("modelVersion", "latest")),
            "systemPrompt": str(config.get("systemPrompt", "")),
            "skills": list(config.get("skills") or metadata.capabilities),
            "tools": list(config.get("tools") or []),
            "allowedProjectIds": list(
                config.get("allowedProjectIds") or self._projects.keys()
            ),
            "maxConcurrentTasks": int(config.get("maxConcurrentTasks", 1)),
            "timeoutSeconds": int(config.get("timeoutSeconds", 1800)),
            "retryPolicy": {
                "maxRetries": int(
                    retry.get("maxRetries", retry.get("maxAttempts", 0))
                ),
                "backoff": str(retry.get("backoff", "none")),
                "backoffSeconds": int(retry.get("backoffSeconds", 0)),
            },
        }

    def get_agent_runs(self, agent_id: str) -> list[dict[str, Any]]:
        if self._metadata(agent_id) is None:
            return []
        entries: list[dict[str, Any]] = []
        for run in self._runs():
            for result in run.results:
                if result.agent_id != agent_id:
                    continue
                entries.append({
                    "taskId": run.task_id,
                    "projectId": run.project_id,
                    "title": run.task_id,
                    "status": _RESULT_STATUS_MAP.get(str(result.status), "Running"),
                    "startedAt": _iso(run.started_at),
                    "durationSec": float(result.metrics.duration_seconds),
                })
        return entries

    # ------------------------------------------------------------------
    # tasks
    # ------------------------------------------------------------------
    @staticmethod
    def _task_title(run: WorkflowExecution) -> str:
        title = run.context.get("title") if isinstance(run.context, Mapping) else None
        return title if isinstance(title, str) and title else run.task_id

    def _workflow_type(self, run: WorkflowExecution) -> str:
        value = run.context.get("workflowType") if isinstance(run.context, Mapping) else None
        return value if value in _WORKFLOW_TYPES else "feature-development"

    def _task_status(self, run: WorkflowExecution) -> str:
        stage = run.state.stage
        if stage in _TASK_STATUSES:
            return stage
        kind = self._stage_kind(run, stage)
        if kind == "INITIAL":
            return "NEW"
        if kind == "ESCALATED":
            candidate = stage.removesuffix("_ESCALATED") + "_REVIEW"
            return candidate if candidate in _TASK_STATUSES else "IMPLEMENTING"
        if kind in _TERMINAL_STAGES:
            return str(kind)
        return "IMPLEMENTING"

    def _task_view(self, run: WorkflowExecution) -> dict[str, Any]:
        step = self._step_for_stage(run, run.state.stage)
        assigned = self._agent_id_for_type(step.agent_type) if step is not None else None
        priority = run.context.get("priority") if isinstance(run.context, Mapping) else None
        if priority == "NORMAL" or priority not in _PRIORITIES:
            priority = "MEDIUM"
        view: dict[str, Any] = {
            "id": run.task_id,
            "title": self._task_title(run),
            "projectId": run.project_id,
            "workflowType": self._workflow_type(run),
            "status": self._task_status(run),
            "priority": priority,
            "createdAt": _iso(run.started_at),
            "updatedAt": _iso(run.updated_at),
            "revisions": sum(run.state.revisions.values()),
        }
        if assigned is not None:
            view["assignedAgentId"] = assigned
        if run.state.stage in _TERMINAL_STAGES:
            view["durationSec"] = max(
                0.0, (run.updated_at - run.started_at).total_seconds()
            )
        return view

    def list_tasks(
        self, filter: Mapping[str, Any] | None = None, **kwargs: Any,
    ) -> list[dict[str, Any]]:
        criteria: dict[str, Any] = {**(filter or {}), **kwargs}
        latest: dict[str, WorkflowExecution] = {}
        for run in sorted(self._runs(), key=lambda item: item.updated_at):
            latest[run.task_id] = run
        views = [self._task_view(run) for run in latest.values()]
        if criteria.get("projectId"):
            views = [v for v in views if v["projectId"] == criteria["projectId"]]
        if criteria.get("agentId"):
            views = [v for v in views if v.get("assignedAgentId") == criteria["agentId"]]
        if criteria.get("status"):
            views = [v for v in views if v["status"] == criteria["status"]]
        if criteria.get("workflowType"):
            views = [v for v in views if v["workflowType"] == criteria["workflowType"]]
        if criteria.get("priority"):
            views = [v for v in views if v["priority"] == criteria["priority"]]
        if criteria.get("sinceHours"):
            reference = self._now() or max(
                (run.updated_at for run in latest.values()), default=None
            )
            if reference is not None:
                cutoff = reference - timedelta(hours=float(criteria["sinceHours"]))
                views = [
                    v for v in views
                    if datetime.fromisoformat(v["createdAt"]) >= cutoff
                ]
        return sorted(views, key=lambda view: view["updatedAt"], reverse=True)

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        return next((v for v in self.list_tasks() if v["id"] == task_id), None)

    # ------------------------------------------------------------------
    # workflows
    # ------------------------------------------------------------------
    def _is_review_stage(self, run: WorkflowExecution) -> bool:
        """True for generated ``<STEP>_REVIEW`` stages of approval steps.

        Note the code-review step's plain stage is literally ``CODE_REVIEW``,
        so a naive ``endswith("_REVIEW")`` check would misclassify it; the
        stage must belong to a step that actually requires approval.
        """
        step = self._step_for_stage(run, run.state.stage)
        return bool(
            step is not None and step.requires_approval
            and run.state.stage == f"{step.stage}_REVIEW"
        )

    def _workflow_status(self, run: WorkflowExecution) -> str:
        try:
            raw = str(self._engine.workflow_run(run.id)["status"])
        except Exception:
            raw = "COMPLETED" if run.state.stage == "COMPLETED" else "RUNNING"
        if raw in _TERMINAL_STAGES:
            return raw
        if self._is_review_stage(run):
            return "WAITING_APPROVAL"
        return "RUNNING"

    @staticmethod
    def _stage_before_failure(run: WorkflowExecution) -> str | None:
        """The stage a FAILED run was in when it failed, from its event trail."""
        for observation in reversed(run.observations):
            event = observation.event
            if event is None or event.event_type not in (
                "WORKFLOW_STARTED", "WORKFLOW_STAGE_CHANGED",
            ):
                continue
            stage = event.metadata.get("stage")
            if isinstance(stage, str) and stage not in (
                "FAILED", "COMPLETED", "CANCELLED",
            ):
                return stage
        return None

    def _step_states(
        self, run: WorkflowExecution, definition: WorkflowDefinition, status: str,
    ) -> list[dict[str, Any]]:
        sequence = ["NEW"]
        for step in definition.steps:
            sequence.extend(step.generated_stages())
        sequence.extend(["COMPLETED", "FAILED", "CANCELLED"])
        stage = run.state.stage
        current_index = sequence.index(stage) if stage in sequence else None
        produced = {artifact.type for artifact in run.artifact_history.values()}
        # The generic FAILED rule below ("first step whose outputs are
        # missing from the artifact history") misattributes any failure
        # that happens after every artifact exists at least once: a run
        # that died inside the code-fix loop, or crashed on a later
        # cycle's re-review / re-test, would blame the next step (CI,
        # which produces nothing). The run's event trail records the
        # stage it actually died in, so blame that step instead: for
        # the fix loop, the step whose verdict triggered the fix (Run
        # tests when a test report exists, otherwise Review code); for
        # any other stage, the step that generates that stage.
        forced_failed: str | None = None
        if status == "FAILED":
            failed_stage = self._stage_before_failure(run)
            if failed_stage == FIX_STAGE:
                if "TEST_REPORT" in run.artifacts:
                    forced_failed = "testing"
                elif "CODE_REVIEW" in run.artifacts:
                    forced_failed = "code_review"
            elif failed_stage is not None:
                for candidate in definition.steps:
                    if failed_stage not in candidate.generated_stages():
                        continue
                    mapped = (
                        _STEP_ID_BY_STEP_ID.get(candidate.id)
                        or _STEP_ID_BY_STAGE.get(candidate.stage)
                    )
                    if mapped in _DASHBOARD_STEP_IDS:
                        forced_failed = mapped
                    break
        steps: list[dict[str, Any]] = []
        failure_marked = False
        for step in definition.steps:
            main_id = _STEP_ID_BY_STEP_ID.get(step.id) or _STEP_ID_BY_STAGE.get(step.stage)
            if main_id is None or main_id not in _DASHBOARD_STEP_IDS:
                continue
            stages = step.generated_stages()
            indexes = [sequence.index(name) for name in stages]
            if status == "COMPLETED":
                main_state = "done"
            elif stage in stages:
                if stage.endswith("_REJECTED"):
                    main_state = "rejected"
                elif step.requires_approval and stage.endswith(("_REVIEW", "_APPROVED")):
                    main_state = "done"
                else:
                    main_state = "active"
            elif status == "FAILED":
                if main_id == forced_failed and not failure_marked:
                    main_state, failure_marked = "failed", True
                elif step.produces and set(step.produces) <= produced:
                    main_state = "done"
                elif not failure_marked:
                    main_state, failure_marked = "failed", True
                else:
                    main_state = "pending"
            elif current_index is not None:
                main_state = "done" if max(indexes) < current_index else "pending"
            elif status == "CANCELLED":
                main_state = (
                    "done" if step.produces and set(step.produces) <= produced
                    else "cancelled"
                )
            else:
                main_state = "pending"
            steps.append({"id": main_id, "label": step.name, "state": main_state})
            approval_id = _APPROVAL_STEP_IDS.get(main_id)
            if step.requires_approval and approval_id is not None:
                steps.append({
                    "id": approval_id,
                    "label": f"{step.name} approval",
                    "state": self._approval_step_state(
                        step, stage, current_index, sequence, status,
                    ),
                })
        return steps

    @staticmethod
    def _approval_step_state(
        step: WorkflowStepDef, stage: str, current_index: int | None,
        sequence: list[str], status: str,
    ) -> str:
        if status == "COMPLETED":
            return "done"
        if stage == f"{step.stage}_REVIEW" or stage == f"{step.stage}_ESCALATED":
            return "active"
        if stage == f"{step.stage}_REJECTED":
            return "rejected"
        if stage == f"{step.stage}_APPROVED":
            return "done"
        review_index = sequence.index(f"{step.stage}_REVIEW")
        if current_index is not None:
            return "done" if current_index > review_index else "pending"
        return "pending"

    @staticmethod
    def _run_error(run: WorkflowExecution, status: str) -> dict[str, Any] | None:
        """The failure that ended a FAILED run, for the dashboard banner.

        The last recorded error is the one that failed the run: an engine
        failure appends its error last, and a failed agent result's errors
        are recorded just before the FAIL transition. Without this, a
        failed run showed a red step but never the reason.
        """
        if status != "FAILED" or not run.errors:
            return None
        error = run.errors[-1]
        return {
            "code": error.code,
            "message": error.message,
            "category": error.category,
            "at": _iso(error.timestamp),
            "details": error.details or None,
            # The stage the run died in (from its event trail), so the
            # banner can name the code-fix loop instead of blaming the
            # step whose verdict triggered it.
            "stage": FactoryService._stage_before_failure(run),
        }

    def _workflow_view(self, run: WorkflowExecution) -> dict[str, Any]:
        definition = self._definition(run)
        status = self._workflow_status(run)
        steps = self._step_states(run, definition, status) if definition else []
        return {
            "id": run.id,
            "taskId": run.task_id,
            "title": self._task_title(run),
            "projectId": run.project_id,
            "type": self._workflow_type(run),
            "status": status,
            "error": self._run_error(run, status),
            "steps": steps,
            "startedAt": _iso(run.started_at),
            "updatedAt": _iso(run.updated_at),
            # Full artifact history (every version, in creation order) with
            # readable content, so a failed run can be diagnosed from the
            # dashboard — e.g. the TEST_REPORT carries each test command's
            # exit code and output. Before this, artifact content was only
            # exposed on the approval view, leaving failed runs opaque.
            "artifacts": [
                {
                    "id": artifact.id,
                    "type": artifact.type,
                    "name": artifact.name,
                    "version": artifact.version,
                    "createdBy": artifact.created_by,
                    "content": self._artifact_text(artifact),
                }
                for artifact in run.artifact_history.values()
            ],
        }

    def list_workflows(self) -> list[dict[str, Any]]:
        return [self._workflow_view(run) for run in self._runs()]

    def get_workflow(self, workflow_id: str) -> dict[str, Any] | None:
        runs = self._runs()
        run = next((item for item in runs if item.id == workflow_id), None)
        if run is None:
            by_task = [item for item in runs if item.task_id == workflow_id]
            run = by_task[-1] if by_task else None
        return self._workflow_view(run) if run is not None else None

    # ------------------------------------------------------------------
    # projects
    # ------------------------------------------------------------------
    def list_projects(self) -> list[dict[str, Any]]:
        runs = self._runs()
        agent_ids = [metadata.id for metadata in self._metadata_list()]
        projects: list[dict[str, Any]] = []
        for project_id, profile in self._projects.items():
            own = [run for run in runs if run.project_id == project_id]
            completed = sum(run.state.stage == "COMPLETED" for run in own)
            failed = sum(run.state.stage == "FAILED" for run in own)
            finished = completed + failed
            metrics: dict[str, Any] = {
                "activeAgents": len({
                    result.agent_id for run in own for result in run.results
                }),
                "running": sum(run.state.stage not in _TERMINAL_STAGES for run in own),
                "completed": completed,
                "failed": failed,
                "successRate": completed / finished if finished else 0.0,
                "pendingApprovals": sum(
                    self._is_review_stage(run) for run in own
                ),
            }
            if self._metrics is not None and hasattr(self._metrics, "project_outcomes"):
                try:
                    outcomes = self._metrics.project_outcomes(project_id)
                except Exception:
                    outcomes = None
                if isinstance(outcomes, Mapping):
                    for key, value in outcomes.items():
                        camel = _camelize(str(key))
                        if camel in metrics and isinstance(value, (int, float)):
                            metrics[camel] = value
            projects.append({
                "id": profile["id"],
                "name": profile["name"],
                "repositoryProvider": profile["repositoryProvider"],
                "repositoryUrl": profile["repositoryUrl"],
                "repositoryPath": profile["repositoryPath"],
                "testCommands": profile["testCommands"],
                "technologies": profile["technologies"],
                "description": profile["description"],
                "workflow": profile["workflow"],
                "enabledSkills": profile["enabledSkills"],
                "technologyGroups": profile["technologyGroups"],
                "approvalChannel": profile["approvalChannel"],
                "agentIds": agent_ids,
                "ci": "UNKNOWN",
                "ciFailures24h": 0,
                "metrics": metrics,
            })
        return projects

    def create_project(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Register a new project; returns its dashboard project view.

        ``payload`` is the project-profile shape used by ``projects/*.yaml``
        (camelCase keys), validated exactly like a profile file: the profile
        must validate against :class:`ProjectProfile` and the id must be a
        slug, because assemblies persist it as ``<id>.yaml``. The optional
        ``on_project_created`` hook runs before the project becomes visible,
        so a persistence failure leaves the registry unchanged.
        """
        profile = self._validate_profile(payload)
        if _PROJECT_ID_PATTERN.fullmatch(profile.id) is None:
            raise ValueError(
                "Project id must be a slug: lowercase letters, digits, '-' or "
                "'_', starting with a letter or digit",
            )
        if profile.id in self._projects:
            raise ProjectExistsError(f"Project '{profile.id}' already exists")
        if self._on_project_created is not None:
            self._on_project_created(profile)
        self._register_project(profile)
        return self._project_view(profile.id)

    @staticmethod
    def _validate_profile(payload: Mapping[str, Any]) -> ProjectProfile:
        try:
            return ProjectProfile.model_validate(dict(payload))
        except ValidationError as error:
            details = "; ".join(
                f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
                for item in error.errors()
            )
            raise ValueError(f"Invalid project profile: {details}") from error

    def _register_project(self, profile: ProjectProfile) -> None:
        self._projects[profile.id] = self._normalize_project(profile.id, profile)
        self._project_profiles[profile.id] = profile.to_contract()

    def _project_view(self, project_id: str) -> dict[str, Any]:
        return next(
            view for view in self.list_projects() if view["id"] == project_id
        )

    def update_project(
        self, project_id: str, payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Replace a project's profile; returns its dashboard project view.

        The payload is merged over the stored profile, so fields the caller
        does not manage (e.g. ``repository.url`` or approval reviewers added
        by hand in the profile file) survive a dashboard edit. The id is the
        project's identity and cannot change; the optional
        ``on_project_updated`` hook runs before the change becomes visible.
        """
        if project_id not in self._projects:
            raise ProjectNotFoundError(f"Project '{project_id}' not found")
        merged = deep_merge(
            self._project_profiles.get(project_id, {}), dict(payload),
        )
        profile = self._validate_profile(merged)
        if profile.id != project_id:
            raise ValueError("Project id cannot be changed")
        if self._on_project_updated is not None:
            self._on_project_updated(profile)
        self._register_project(profile)
        return self._project_view(project_id)

    def delete_project(self, project_id: str) -> None:
        """Remove a project, unless it still has non-terminal runs.

        Historical (terminal) runs stay visible in the task/workflow views;
        the optional ``on_project_deleted`` hook runs before removal, so a
        persistence failure leaves the registry unchanged.
        """
        if project_id not in self._projects:
            raise ProjectNotFoundError(f"Project '{project_id}' not found")
        active = [
            run for run in self._runs()
            if run.project_id == project_id
            and run.state.stage not in _TERMINAL_STAGES
        ]
        if active:
            raise ProjectConflictError(
                f"Project '{project_id}' has {len(active)} active run(s)",
            )
        if self._on_project_deleted is not None:
            self._on_project_deleted(project_id)
        del self._projects[project_id]
        self._project_profiles.pop(project_id, None)

    # ------------------------------------------------------------------
    # approvals
    # ------------------------------------------------------------------
    @staticmethod
    def _artifact_text(artifact: Any | None) -> str | None:
        """Full readable content of an artifact, for the approval view.

        Text artifacts contribute their ``text`` body; structured payloads
        (e.g. a CODE changeset) are rendered as indented JSON so a reviewer
        can read exactly what they are approving.
        """
        if artifact is None:
            return None
        content = artifact.content
        if isinstance(content, str):
            return content
        if isinstance(content, Mapping):
            text = content.get("text")
            if isinstance(text, str):
                return text
            return json.dumps(content, indent=2, ensure_ascii=False, default=str)
        return None

    @staticmethod
    def _artifact_summary(artifact: Any | None) -> str:
        if artifact is None:
            return ""
        content = artifact.content
        text: str | None = None
        if isinstance(content, Mapping):
            candidate = content.get("text")
            text = candidate if isinstance(candidate, str) else None
        elif isinstance(content, str):
            text = content
        if not text:
            return ""
        for line in text.splitlines():
            if line.strip():
                return line.strip().lstrip("#").strip()
        return ""

    def _approval_view(self, run: WorkflowExecution, request: Any) -> dict[str, Any]:
        artifact = run.artifact_history.get(request.artifact_id)
        if artifact is not None:
            requested_by = artifact.created_by
            artifact_name = artifact.name
        else:
            step_id = (request.metadata or {}).get("stepId")
            definition = self._definition(run)
            step = next(
                (item for item in definition.steps if item.id == step_id), None,
            ) if definition is not None else None
            requested_by = (
                self._agent_id_for_type(step.agent_type) if step is not None else None
            ) or request.requested_by
            artifact_name = request.artifact_id
        requested_at = getattr(request, "requested_at", None) or getattr(
            request, "created_at", None,
        )
        view: dict[str, Any] = {
            "id": request.id,
            "projectId": run.project_id,
            "taskId": run.task_id,
            "type": request.type if request.type in _APPROVAL_TYPES else "SPEC",
            "status": "PENDING",
            "requestedAt": _iso(requested_at or run.updated_at),
            "requestedByAgentId": requested_by,
            "artifact": artifact_name,
            "summary": self._artifact_summary(artifact),
            "comments": [],
        }
        content = self._artifact_text(artifact)
        if content:
            view["artifactContent"] = content
        return view

    def list_approvals(self) -> list[dict[str, Any]]:
        approvals: list[dict[str, Any]] = []
        for run in self._runs():
            if run.approval_id is None:
                continue
            try:
                request = self._engine.pending_approval(run.id)
            except (ApprovalError, KeyError, ValueError):
                continue
            approvals.append(self._approval_view(run, request))
        return approvals

    def decide_approval(
        self, approval_id: str, *, decision: str, comment: str = "",
    ) -> dict[str, Any]:
        if decision not in (*_DECISIONS, "COMMENT"):
            raise ValueError(f"Unknown approval decision: {decision}")
        run = next(
            (item for item in self._runs() if item.approval_id == approval_id), None,
        )
        if run is None:
            raise ApprovalError(
                "NOT_FOUND", "Approval is not pending for any known run",
            )
        request = self._engine.pending_approval(run.id)
        view = self._approval_view(run, request)
        if decision == "COMMENT":
            if comment:
                view["comments"].append({
                    "author": self._reviewer,
                    "at": _iso(self._now() or run.updated_at),
                    "text": comment,
                })
            return view
        engine_decision, dashboard_status = _DECISIONS[decision]
        artifact = run.artifact_history.get(request.artifact_id)
        producing_agent = artifact.created_by if artifact is not None else None
        self._engine.decide(
            run.id, reviewer=self._reviewer, decision=engine_decision,  # type: ignore[arg-type]
            comment=comment, expected_approval_id=approval_id,
        )
        # Metrics are keyed by agent id (as in AgentResult.agent_id), so the
        # approval outcome must be recorded under the same id, not the type.
        self._record_approval_decision(run, producing_agent, engine_decision)
        decided_run = self._engine.get(run.id)
        # A multi-approval quorum may leave the same request still pending.
        view["status"] = (
            "PENDING" if decided_run.approval_id == approval_id else dashboard_status
        )
        if comment:
            view["comments"].append({
                "author": self._reviewer,
                "at": _iso(self._now() or decided_run.updated_at),
                "text": comment,
            })
        if view["status"] != "PENDING":
            # The gate is cleared: the run continues on its own to the
            # next approval gate (or to completion) — no manual tick.
            self._drive_in_background(run.id)
        return view

    def _record_approval_decision(
        self, run: WorkflowExecution, agent_id: str | None, decision: str,
    ) -> None:
        if not agent_id:
            return
        if self._metrics is None or not hasattr(self._metrics, "record_approval_decision"):
            return
        record = getattr(self._metrics, "record_approval_decision")
        try:
            record(
                project_id=run.project_id, task_id=run.task_id,
                agent_id=agent_id, decision=decision, at=None,
            )
        except TypeError:
            try:
                record(
                    project_id=run.project_id, task_id=run.task_id,
                    agent_id=agent_id, decision=decision,
                )
            except Exception:  # nosec B110
                pass
        except Exception:  # nosec B110
            pass

    # ------------------------------------------------------------------
    # activity
    # ------------------------------------------------------------------
    @staticmethod
    def _activity_view(event: ActivityEvent) -> dict[str, Any]:
        event_type = event.event_type or ""
        metadata = event.metadata or {}
        if event_type.startswith("APPROVAL"):
            source_kind = "approval"
        elif str(metadata.get("source", "")).lower() in {
            "integration", "ci", "gitlab", "github",
        } or event_type.startswith(("CI_", "GIT_")):
            source_kind = "integration"
        elif event.agent_id:
            source_kind = "agent"
        else:
            source_kind = "orchestrator"
        source_id = event.agent_id or event.workflow_id or "orchestrator"
        if "FAILED" in event_type or "ERROR" in event_type:
            level = "error"
        elif "REJECT" in event_type or "ESCALAT" in event_type:
            level = "warn"
        elif "COMPLETED" in event_type or "APPROVED" in event_type:
            level = "success"
        else:
            level = "info"
        view: dict[str, Any] = {
            "id": event.id,
            "timestamp": _iso(event.timestamp),
            "sourceKind": source_kind,
            "sourceId": source_id,
            "sourceLabel": source_id,
            "level": level,
            "message": event.message or event_type,
        }
        if event.project_id:
            view["projectId"] = event.project_id
        if event.task_id:
            view["taskId"] = event.task_id
        return view

    def list_activity(
        self, filter: Mapping[str, Any] | None = None, **kwargs: Any,
    ) -> list[dict[str, Any]]:
        criteria: dict[str, Any] = {**(filter or {}), **kwargs}
        events: dict[str, ActivityEvent] = {}
        for run in self._runs():
            for observation in run.observations:
                if observation.event is not None:
                    events.setdefault(observation.event.id, observation.event)
        if self._metrics is not None and hasattr(self._metrics, "events"):
            try:
                for event in self._metrics.events():
                    events.setdefault(event.id, event)
            except Exception:  # nosec B110
                pass
        ordered = sorted(
            events.values(), key=lambda event: event.timestamp, reverse=True,
        )
        views = [self._activity_view(event) for event in ordered]
        if criteria.get("agentId"):
            views = [v for v in views if v["sourceId"] == criteria["agentId"]]
        if criteria.get("taskId"):
            views = [v for v in views if v.get("taskId") == criteria["taskId"]]
        if criteria.get("projectId"):
            views = [v for v in views if v.get("projectId") == criteria["projectId"]]
        if criteria.get("limit") is not None:
            views = views[: int(criteria["limit"])]
        return views

    # ------------------------------------------------------------------
    # metrics overview
    # ------------------------------------------------------------------
    def get_metrics_overview(self) -> dict[str, Any]:
        if self._metrics is not None and hasattr(self._metrics, "overview"):
            try:
                raw = self._metrics.overview()
            except Exception:
                raw = None
            if isinstance(raw, Mapping):
                return dict(raw)
        return {
            "daily": [],
            "human": dict(_EMPTY_OVERVIEW["human"]),
            "quality": dict(_EMPTY_OVERVIEW["quality"]),
            "agents": [],
        }

    # ------------------------------------------------------------------
    # run control
    # ------------------------------------------------------------------
    # Ceiling on automatic step executions per drive. A full workflow
    # needs ~11 ticks plus bounded fix rounds — far below this; the cap
    # only guards against a pathological no-progress loop.
    _DRIVE_LIMIT = 100

    # Drives run on background threads: a step can sit in a model call
    # for minutes, and driving on the request thread froze the whole
    # API — the dashboard could not even load its lists until the call
    # returned. The stores keep one connection per thread, so request
    # threads and drive threads never share a connection object.
    def _drive_in_background(self, run_id: str) -> None:
        """Start a drive thread for a run (coalesced per run)."""
        with self._drive_lock:
            if run_id in self._drive_threads:
                return
            thread = threading.Thread(
                target=self._drive_worker, args=(run_id,),
                name=f"asf-drive-{run_id[:8]}", daemon=True,
            )
            self._drive_threads[run_id] = thread
        thread.start()

    def _drive_worker(self, run_id: str) -> None:
        try:
            self._drive(run_id)
        finally:
            with self._drive_lock:
                self._drive_threads.pop(run_id, None)
            # A cancel requested just as the drive parked (e.g. the run
            # reached an approval gate in the same moment) must not be
            # lost with the thread: nobody is dispatching now, so the
            # cancellation can be applied directly.
            self._apply_requested_cancel(run_id)

    def _wait_for_drive(self, run_id: str, timeout: float | None = None) -> None:
        """Join a run's drive thread if one is active."""
        with self._drive_lock:
            thread = self._drive_threads.get(run_id)
        if thread is not None:
            thread.join(timeout)

    def wait_for_drives(self, timeout: float | None = None) -> None:
        """Block until every background drive finishes (tests/shutdown)."""
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            with self._drive_lock:
                threads = list(self._drive_threads.values())
            if not threads:
                return
            for thread in threads:
                remaining = (
                    None if deadline is None
                    else max(0.0, deadline - time.monotonic())
                )
                thread.join(remaining)
            if deadline is not None and time.monotonic() >= deadline:
                return

    def _drive(self, run_id: str) -> None:
        """Advance a run automatically until it needs a human or stops.

        Ticks while the run is RUNNING and each tick makes progress, so a
        run flows on its own from one approval gate to the next — and
        through the code/test/fix steps in between — without anyone
        pressing a "next step" button. Stops at approval gates
        (WAITING_APPROVAL), terminal stages, scheduled retries (the tick
        makes no progress until the backoff is due) and escalations.
        Best-effort by design: a dispatch problem (e.g. an interrupted
        run awaiting recover()) stops the drive and leaves the run for
        manual handling instead of failing the request that triggered it.
        """
        for _ in range(self._DRIVE_LIMIT):
            if self._apply_requested_cancel(run_id):
                break
            run = self._engine.get(run_id)
            if self._workflow_status(run) != "RUNNING":
                break
            before = (run.state.stage, len(run.results))
            try:
                self._engine.tick(run_id)
            except Exception:
                break
            if self._apply_requested_cancel(run_id):
                break
            after = self._engine.get(run_id)
            if (after.state.stage, len(after.results)) == before:
                break
        try:
            self._engine.flush_observations(run_id)
        except (RuntimeError, ValueError):
            # ValueError: another thread is dispatching this run right
            # now (a manual tick racing the drive) and the engine will
            # not flush mid-dispatch. At-least-once delivery; retried
            # on a later flush.
            pass

    def drive_run(self, run_id: str) -> dict[str, Any] | None:
        """Auto-advance a run to its next stopping point; returns its view."""
        self._wait_for_drive(run_id)
        self._drive(run_id)
        return self.get_workflow(run_id)

    def drive_active_runs(self) -> None:
        """Auto-advance every known mid-flight run (used at API startup).

        A run left at a work stage by a backend restart continues to its
        next approval gate on its own. A run left with ``in_flight`` set
        had its dispatch interrupted by the stop — at startup nothing
        can still be in flight, so the stale marker is recovered
        (the interrupted step replays) instead of stranding the run.
        """
        for run in self._runs():
            if run.in_flight is not None:
                try:
                    self._engine.recover(
                        run.id,
                        reason="API startup: the previous backend stopped"
                        " mid-dispatch",
                        retry_interrupted=True,
                    )
                except Exception:
                    continue
                run = self._engine.get(run.id)
            if self._workflow_status(run) == "RUNNING":
                self._drive_in_background(run.id)

    def start_run(
        self,
        task_id: str,
        project_id: str,
        inputs: Mapping[str, Any] | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> WorkflowExecution:
        run = self._engine.start(
            task_id=task_id, project_id=project_id, inputs=inputs, context=context,
        )
        self.track(run.id)
        self._drive_in_background(run.id)
        return self._engine.get(run.id)

    def tick_run(self, run_id: str) -> dict[str, Any] | None:
        # A manual tick must not race the run's background drive: wait
        # for the drive to park the run, then tick (usually a no-op).
        self._wait_for_drive(run_id)
        self._engine.tick(run_id)
        try:
            self._engine.flush_observations(run_id)
        except RuntimeError:
            pass  # Observation delivery is at-least-once; a retry happens later.
        return self.get_workflow(run_id)

    def cancel_run(self, run_id: str) -> dict[str, Any] | None:
        """Cancel an active run; a cancelled run is terminal.

        A run parked at an approval gate (or otherwise not being driven)
        is cancelled immediately, including its pending approval. A run
        whose background drive is mid-step cannot be mutated safely —
        the engine refuses — so the request is recorded and the drive
        applies the cancellation as soon as the current step returns;
        the returned view then still shows the run as active, with the
        cancellation taking effect moments later. Cancelling a run that
        already finished raises ``ValueError`` (the API maps it to 409).
        """
        run = self._engine.get(run_id)
        if run.state.stage in _TERMINAL_STAGES:
            raise ValueError(
                f"Run '{run_id}' is already {run.state.stage.lower()}; "
                "only an active run can be cancelled",
            )
        with self._drive_lock:
            driving = run_id in self._drive_threads
            if driving:
                self._cancel_requested.add(run_id)
            else:
                self._cancel_requested.discard(run_id)
        if driving:
            return self.get_workflow(run_id)
        self._engine.cancel(run_id)
        return self.get_workflow(run_id)

    def _apply_requested_cancel(self, run_id: str) -> bool:
        """Cancel ``run_id`` if a cancel was requested for it.

        Called by the drive between steps, when no dispatch is in
        flight. Returns True when the run was cancelled.
        """
        with self._drive_lock:
            requested = run_id in self._cancel_requested
            self._cancel_requested.discard(run_id)
        if not requested:
            return False
        try:
            self._engine.cancel(run_id)
        except Exception:
            return False
        return True

    def retry_run(self, run_id: str) -> dict[str, Any] | None:
        """Start a fresh run of a finished run's task, with its original inputs.

        A run is an immutable execution record and FAILED is terminal, so
        "run it again" means a new execution of the same task rather than
        resurrecting the old one. The engine persists each run's inputs, so
        the retry replays exactly what the original run was given — the
        requirement included — while the project context (test commands,
        review rules) is rebuilt from the project's current configuration.
        Only terminal runs qualify; a live run raises ``ValueError``.
        """
        run = self._engine.get(run_id)
        if run.state.stage not in _TERMINAL_STAGES:
            raise ValueError(
                f"Run '{run_id}' is still active at stage {run.state.stage}; "
                "only a completed, failed or cancelled run can be run again",
            )
        context = {
            key: run.context[key]
            for key in ("title", "priority", "workflowType")
            if isinstance(run.context, Mapping) and run.context.get(key) is not None
        }
        new_run = self.start_run(
            run.task_id, run.project_id,
            inputs=dict(run.inputs), context=context or None,
        )
        return self.get_workflow(new_run.id)

    def resume_run(self, run_id: str) -> dict[str, Any] | None:
        """Continue a FAILED run from the step that failed, in a new run.

        Unlike :meth:`retry_run` (a fresh execution from the first step),
        the resumed run inherits the failed run's artifacts and approvals:
        the spec, plan and task breakdown are neither rewritten nor
        re-approved — only the failed step and what follows it execute
        again. The failed run itself stays untouched as the record of
        the failure. A run that has not failed raises ``ValueError``.
        """
        run = self._engine.resume_failed(run_id)
        self.track(run.id)
        self._drive_in_background(run.id)
        return self.get_workflow(run.id)
