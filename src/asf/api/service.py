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
import logging
import os
import re
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from pydantic import ValidationError

from asf.agents._shared.skills import agent_skill_ids
from asf.api.hosting_tokens import HostingTokens
from asf.api.scheduler import RunScheduler
from asf.approval.errors import ApprovalError
from asf.configuration.project import ProjectProfile
from asf.configuration.yamlio import deep_merge
from asf.contracts.models import ActivityEvent
from asf.integrations.hosting.factory import DEFAULT_TOKEN_ENVS
from asf.orchestrator.code_loop import FIX_STAGE
from asf.orchestrator.engine import Orchestrator
from asf.orchestrator.execution import WorkflowExecution
from asf.orchestrator.ports import ConcurrentModificationError
from asf.state_machine.graph import build_graph
from asf.state_machine.status import kind_of
from asf.workflow.definition import WorkflowDefinition, WorkflowStepDef

logger = logging.getLogger("asf.api.service")


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

# Automatic model routing: a run whose requirement exceeds this many
# characters is classified "complex" at start (context key modelTier)
# and every agent call is upgraded to the shared configured model —
# long requirements produce long specs/plans/code, which are exactly
# what the economy per-agent models truncate or mis-format. Below the
# threshold, runs route per agent as configured and stay cheap.
COMPLEX_REQUIREMENT_CHARS = 6000

# Automatic task splitting: a requirement beyond this size is first
# decomposed into sub-tasks (child runs under the original task id,
# executed one at a time in order) when a decomposer is configured.
# A decomposition failure never blocks the task: it runs whole and
# the failure is recorded on the run (context key splitError,
# exposed in the workflow view).
SPLIT_REQUIREMENT_CHARS = 12_000

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
        hosting_tokens: HostingTokens | None = None,
        decomposer: Any = None,
        max_concurrent_runs: int = 2,
        on_run_terminal: Callable[[str, str, str], None] | None = None,
    ) -> None:
        if max_concurrent_runs < 1:
            raise ValueError("max_concurrent_runs must be at least 1")
        # Optional assembly hook fired when a run reaches a terminal
        # stage (run_id, project_id, stage) — the demo uses it to
        # clean up the run's git worktree. Best-effort: failures are
        # logged, never allowed to break a drive.
        self._on_run_terminal = on_run_terminal
        self._engine = engine
        self._metrics = metrics
        self._store = store
        self._reviewer = reviewer
        self._on_project_created = on_project_created
        self._on_project_updated = on_project_updated
        self._on_project_deleted = on_project_deleted
        self._model_settings = model_settings
        self._hosting_tokens = hosting_tokens
        self._decomposer = decomposer
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
        # Retry scheduler: wakes runs when their retry_at comes due so
        # a scheduled retry resumes on its own (see api/scheduler.py).
        # Its clock resolves lazily so stub engines in tests (which
        # carry no clock) can still assemble a service.
        self._scheduler = RunScheduler(
            clock=self._scheduler_clock,
            wake=self._drive_in_background,
        )
        self._projects = {
            pid: self._normalize_project(pid, profile) for pid, profile in projects.items()
        }
        self._tracked: list[str] = []
        self._store_runs: dict[str, WorkflowExecution] = {}
        # Background drives run on a bounded pool of daemon workers
        # (see _drive_in_background): at most max_concurrent_runs runs
        # are driven at once; further drives queue. _drive_lock guards
        # the pool state AND the cancel set together, which keeps the
        # cancel-vs-drive-finish interleavings airtight (a cancel is
        # either seen by the active drive or applied synchronously).
        self._max_concurrent_runs = max_concurrent_runs
        self._drive_lock = threading.Lock()
        self._drive_condition = threading.Condition(self._drive_lock)
        self._drive_active: set[str] = set()
        self._drive_queue: deque[str] = deque()
        self._drive_workers: list[threading.Thread] = []
        self._drive_stopped = False
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
            # The catalogue skills that apply to this agent type —
            # the same set its prompt builder injects on runs whose
            # project enables them.
            "skills": agent_skill_ids(str(metadata.type)),
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
            "skills": list(
                config.get("skills")
                or agent_skill_ids(str(metadata.type))
                or metadata.capabilities
            ),
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

    @staticmethod
    def _task_priority(run: WorkflowExecution) -> str:
        priority = run.context.get("priority") if isinstance(run.context, Mapping) else None
        if priority == "NORMAL" or priority not in _PRIORITIES:
            return "MEDIUM"
        return str(priority)

    def _task_view(self, run: WorkflowExecution) -> dict[str, Any]:
        step = self._step_for_stage(run, run.state.stage)
        assigned = self._agent_id_for_type(step.agent_type) if step is not None else None
        view: dict[str, Any] = {
            "id": run.task_id,
            "title": self._task_title(run),
            "projectId": run.project_id,
            "workflowType": self._workflow_type(run),
            "status": self._task_status(run),
            "priority": self._task_priority(run),
            "createdAt": _iso(run.started_at),
            "updatedAt": _iso(run.updated_at),
            "revisions": sum(run.state.revisions.values()),
        }
        if assigned is not None:
            view["assignedAgentId"] = assigned
        # Split lineage: a part task names its parent so the task
        # list can nest it under the parent's row (see list_tasks).
        split = run.context.get("split") if isinstance(run.context, Mapping) else None
        if isinstance(split, Mapping) and isinstance(split.get("parentTaskId"), str):
            view["parentTaskId"] = split["parentTaskId"]
            if isinstance(split.get("index"), int):
                view["splitIndex"] = split["index"]
            if isinstance(split.get("total"), int) and split["total"] > 0:
                view["splitTotal"] = split["total"]
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
        views.extend(
            view for view in self._split_parent_views(latest)
            if view["id"] not in {v["id"] for v in views}
        )
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
        views = sorted(views, key=lambda view: view["updatedAt"], reverse=True)
        return FactoryService._group_split_parts(views)

    @staticmethod
    def _group_split_parts(views: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Nest auto-split parts directly under their parent row.

        The flat list is sorted by recency, so a split task's parts
        would scatter across it with no visible link to the parent.
        Parts whose parent row is present move to directly beneath
        it, in split order; everything else keeps its sorted place,
        and a part whose parent was filtered out stays top-level
        rather than disappearing.
        """
        parents = {view["id"] for view in views if view.get("isSplitParent")}
        if not parents:
            return views
        children: dict[str, list[dict[str, Any]]] = {}
        for view in views:
            parent = view.get("parentTaskId")
            if isinstance(parent, str) and parent in parents:
                children.setdefault(parent, []).append(view)
        grouped: list[dict[str, Any]] = []
        for view in views:
            parent = view.get("parentTaskId")
            if isinstance(parent, str) and parent in parents:
                continue  # emitted under its parent below
            grouped.append(view)
            if view["id"] in children:
                grouped.extend(
                    sorted(
                        children[view["id"]],
                        key=lambda child: child.get("splitIndex") or 0,
                    )
                )
        return grouped

    def _split_parent_views(
        self, latest: Mapping[str, WorkflowExecution],
    ) -> list[dict[str, Any]]:
        """Synthesize task rows for auto-split parents.

        A split parent has no run of its own — its child parts do —
        so without this it would be invisible in the task list. The
        row aggregates the latest run of each part: the status of
        the part currently in flight; otherwise FAILED or CANCELLED
        when a part ended that way, COMPLETED when every part has
        completed, and IMPLEMENTING while the chain is between parts.
        """
        children_by_parent: dict[str, list[WorkflowExecution]] = {}
        for run in latest.values():
            split = run.context.get("split") if isinstance(run.context, Mapping) else None
            if isinstance(split, Mapping) and isinstance(split.get("parentTaskId"), str):
                children_by_parent.setdefault(split["parentTaskId"], []).append(run)

        def split_of(run: WorkflowExecution) -> Mapping[str, Any]:
            split = run.context.get("split") if isinstance(run.context, Mapping) else None
            return split if isinstance(split, Mapping) else {}

        views: list[dict[str, Any]] = []
        for parent_id, children in children_by_parent.items():
            if parent_id in latest:
                continue
            children.sort(key=lambda run: split_of(run).get("index") or 0)
            first = children[0]
            total_raw = split_of(first).get("total")
            total = total_raw if isinstance(total_raw, int) and total_raw > 0 else len(children)
            completed = sum(1 for run in children if run.state.stage == "COMPLETED")
            active = next(
                (run for run in reversed(children)
                 if run.state.stage not in _TERMINAL_STAGES),
                None,
            )
            if active is not None:
                status = self._task_status(active)
            elif any(run.state.stage == "FAILED" for run in children):
                status = "FAILED"
            elif any(run.state.stage == "CANCELLED" for run in children):
                status = "CANCELLED"
            elif completed >= total:
                status = "COMPLETED"
            else:
                status = "IMPLEMENTING"
            title = split_of(first).get("title")
            views.append({
                "id": parent_id,
                "title": title if isinstance(title, str) and title else parent_id,
                "projectId": first.project_id,
                "workflowType": self._workflow_type(first),
                "status": status,
                "priority": self._task_priority(first),
                "createdAt": _iso(min(run.started_at for run in children)),
                "updatedAt": _iso(max(run.updated_at for run in children)),
                "revisions": sum(sum(run.state.revisions.values()) for run in children),
                "isSplitParent": True,
                "splitTotal": total,
                "splitCompleted": completed,
            })
        return views

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
    def _trail_stages(run: WorkflowExecution) -> list[str]:
        """The run's stage trail, newest first, terminal stages removed."""
        stages: list[str] = []
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
                stages.append(stage)
        return stages

    @staticmethod
    def _stage_before_failure(run: WorkflowExecution) -> str | None:
        """The stage a FAILED/CANCELLED run was in just before it ended,
        from its event trail."""
        stages = FactoryService._trail_stages(run)
        return stages[0] if stages else None

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
        # For a run that ended (cancelled or failed), the stage it was
        # in when the terminal transition landed (from its event
        # trail): approval steps are judged against it, since the
        # terminal stage itself sits past every step in the sequence
        # and would mark them all done.
        terminal_from_index: int | None = None
        if status in ("CANCELLED", "FAILED"):
            stage_before = self._stage_before_failure(run)
            if stage_before in sequence:
                terminal_from_index = sequence.index(stage_before)
            elif stage_before is not None:
                # The run ended in a stage no definition step generates
                # — the code-fix loop's CODE_FIX is injected by the
                # loop graph, not by a step — so its index lookup fails
                # and every gate would fall back to pending even though
                # the run demonstrably passed them. Judge the gates
                # against the newest defined stage in the trail instead
                # (for the fix loop, the review/test step that triggered
                # it — past every gate). A trail holding nothing else
                # (e.g. a run resumed straight into the fix loop, whose
                # early stage changes predate the fork) still proves
                # every gate was passed: the loop is only reachable
                # after the last approval.
                for trail_stage in self._trail_stages(run):
                    if trail_stage in sequence:
                        terminal_from_index = sequence.index(trail_stage)
                        break
                if terminal_from_index is None and stage_before == FIX_STAGE:
                    approved_indexes = [
                        sequence.index(f"{step.stage}_APPROVED")
                        for step in definition.steps
                        if step.requires_approval
                        and f"{step.stage}_APPROVED" in sequence
                    ]
                    if approved_indexes:
                        terminal_from_index = max(approved_indexes)
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
        skip_ids = set(self._skip_approvals_of(run))
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
            elif status == "CANCELLED":
                # Must precede the current_index fallthrough: a cancelled
                # run's stage is the sequence's last entry, so every step
                # would otherwise read as done. A step counts as done only
                # if it actually published everything it produces; the
                # step in progress at cancel time and everything after it
                # are cancelled, never done.
                main_state = (
                    "done" if step.produces and set(step.produces) <= produced
                    else "cancelled"
                )
            elif current_index is not None:
                main_state = "done" if max(indexes) < current_index else "pending"
            else:
                main_state = "pending"
            steps.append({"id": main_id, "label": step.name, "state": main_state})
            approval_id = _APPROVAL_STEP_IDS.get(main_id)
            if step.requires_approval and approval_id is not None:
                approval_state = self._approval_step_state(
                    step, stage, current_index, sequence, status,
                    terminal_from_index,
                )
                if approval_state == "done" and main_id in skip_ids:
                    # The run passed this gate because the task asked
                    # to skip it — say so instead of implying a human
                    # approved it.
                    approval_state = "skipped"
                steps.append({
                    "id": approval_id,
                    "label": f"{step.name} approval",
                    "state": approval_state,
                })
        return steps

    @staticmethod
    def _approval_step_state(
        step: WorkflowStepDef, stage: str, current_index: int | None,
        sequence: list[str], status: str,
        terminal_from_index: int | None = None,
    ) -> str:
        if status == "COMPLETED":
            return "done"
        if stage == f"{step.stage}_REVIEW" or stage == f"{step.stage}_ESCALATED":
            # A run that died while sitting at this gate is failed, not
            # active — nothing is still being decided on it.
            return "failed" if status == "FAILED" else "active"
        if stage == f"{step.stage}_REJECTED":
            return "rejected"
        if stage == f"{step.stage}_APPROVED":
            return "done"
        if status in ("CANCELLED", "FAILED"):
            # Done only if the run had already passed this gate when it
            # ended; the gate it died at, and every later gate, were
            # never approved — a cancelled run shows them cancelled, a
            # failed run leaves them pending. (Falling through to the
            # index comparison below would mark every gate done, since
            # the terminal stage sits past all of them.)
            fallback = "cancelled" if status == "CANCELLED" else "pending"
            if terminal_from_index is None:
                return fallback
            approved_index = sequence.index(f"{step.stage}_APPROVED")
            return "done" if terminal_from_index >= approved_index else fallback
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

    @staticmethod
    def _current_activity(
        run: WorkflowExecution, steps: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """What the run is doing right now, for the dashboard's live strip.

        Derived at read time from state the engine already persists:
        ``in_flight`` is stamped (and the run saved) before a step
        dispatches, so a run sitting in a minutes-long model call still
        reports which step it is on and since when; ``retry_at`` marks a
        step waiting out its backoff. Terminal and approval-waiting runs
        have no live activity — their own cards explain those states.
        """
        if run.state.stage in _TERMINAL_STAGES:
            return None
        active = next((s for s in steps if s.get("state") == "active"), None)
        base: dict[str, Any] = {
            "stepId": active["id"] if active else None,
            "stepLabel": active["label"] if active else None,
            "stage": run.state.stage,
            "since": _iso(run.updated_at),
        }
        if run.in_flight is not None:
            return {**base, "kind": "STEP_RUNNING", "retryAt": None}
        if run.retry_at is not None:
            return {**base, "kind": "RETRY_WAIT", "retryAt": _iso(run.retry_at)}
        return None

    def _workflow_view(self, run: WorkflowExecution) -> dict[str, Any]:
        definition = self._definition(run)
        status = self._workflow_status(run)
        steps = self._step_states(run, definition, status) if definition else []
        split = run.context.get("split") if isinstance(run.context, Mapping) else None
        if not isinstance(split, Mapping):
            split = {}
        split_error = (
            run.context.get("splitError") if isinstance(run.context, Mapping) else None
        )
        return {
            "id": run.id,
            "taskId": run.task_id,
            "title": self._task_title(run),
            "projectId": run.project_id,
            "type": self._workflow_type(run),
            "status": status,
            "error": self._run_error(run, status),
            # Split lineage: set on the child runs of an auto-split
            # task; splitError is set instead when decomposition was
            # attempted and failed (the run then proceeds whole).
            "parentTaskId": split.get("parentTaskId"),
            "splitIndex": split.get("index"),
            "splitTotal": split.get("total"),
            "splitError": split_error if isinstance(split_error, str) else None,
            # "complex" when the run's requirement was classified as
            # oversized at start: every agent call is upgraded to the
            # shared model (see COMPLEX_REQUIREMENT_CHARS).
            "modelTier": run.context.get("modelTier"),
            # Approval gates this task asked to skip at creation; the
            # matching approval steps render as "skipped" once passed.
            "skippedApprovals": self._skip_approvals_of(run),
            "currentActivity": self._current_activity(run, steps),
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
                **self._hosting_token_view(project_id),
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

    # ------------------------------------------------------------------
    # hosting tokens (per project; write-only, never part of the profile)
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_hosting_token(
        payload: Mapping[str, Any],
    ) -> tuple[dict[str, Any], str | None, bool]:
        """Split the write-only hosting-token fields off a project payload.

        ``hostingToken`` / ``clearHostingToken`` are API fields, not
        profile fields — the profile forbids extras and is persisted to
        YAML, so a secret must never land in it. A non-blank token
        replaces the stored one; the clear flag removes it.
        """
        data = dict(payload)
        token = data.pop("hostingToken", None)
        clear = data.pop("clearHostingToken", False)
        if token is not None and not isinstance(token, str):
            raise ValueError("hostingToken must be a string")
        if not isinstance(clear, bool):
            raise ValueError("clearHostingToken must be a boolean")
        return data, (token.strip() or None) if token else None, clear

    def _require_token_store(self, token: str | None, clear: bool) -> None:
        if (token is not None or clear) and self._hosting_tokens is None:
            raise ValueError(
                "This backend has no hosting-token store; provide the "
                "token through the ASF_GITLAB_TOKEN / ASF_GITHUB_TOKEN "
                "environment variable instead",
            )

    def _apply_hosting_token(
        self, project_id: str, token: str | None, clear: bool,
    ) -> None:
        if self._hosting_tokens is None:
            return
        if clear:
            self._hosting_tokens.clear(project_id)
        if token is not None:
            self._hosting_tokens.set(project_id, token)

    def _hosting_token_view(self, project_id: str) -> dict[str, Any]:
        """Token status for the project view: configured? + last-4 hint.

        The hint exists only for dashboard-stored tokens; an env-provided
        token reports as configured without exposing any of its value.
        """
        if self._hosting_tokens is not None:
            hint = self._hosting_tokens.hint(project_id)
            if hint is not None:
                return {"hostingTokenConfigured": True, "hostingTokenHint": hint}
        profile = self._project_profiles.get(project_id) or {}
        repository = profile.get("repository")
        configured = False
        if isinstance(repository, Mapping):
            provider = str(repository.get("provider") or "").strip().lower()
            if provider in DEFAULT_TOKEN_ENVS and repository.get("url"):
                env_name = str(
                    repository.get("tokenEnv") or DEFAULT_TOKEN_ENVS[provider],
                )
                configured = bool(os.environ.get(env_name))
        return {"hostingTokenConfigured": configured, "hostingTokenHint": None}

    def create_project(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Register a new project; returns its dashboard project view.

        ``payload`` is the project-profile shape used by ``projects/*.yaml``
        (camelCase keys), validated exactly like a profile file: the profile
        must validate against :class:`ProjectProfile` and the id must be a
        slug, because assemblies persist it as ``<id>.yaml``. The optional
        ``on_project_created`` hook runs before the project becomes visible,
        so a persistence failure leaves the registry unchanged.
        """
        data, token, clear = self._extract_hosting_token(payload)
        self._require_token_store(token, clear)
        profile = self._validate_profile(data)
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
        self._apply_hosting_token(profile.id, token, clear)
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
        data, token, clear = self._extract_hosting_token(payload)
        self._require_token_store(token, clear)
        if project_id not in self._projects:
            raise ProjectNotFoundError(f"Project '{project_id}' not found")
        merged = deep_merge(
            self._project_profiles.get(project_id, {}), data,
        )
        profile = self._validate_profile(merged)
        if profile.id != project_id:
            raise ValueError("Project id cannot be changed")
        if self._on_project_updated is not None:
            self._on_project_updated(profile)
        self._register_project(profile)
        self._apply_hosting_token(project_id, token, clear)
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
        if self._hosting_tokens is not None:
            self._hosting_tokens.clear(project_id)

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
            # A split parent's page shows its parts' activity too:
            # the parts are separate runs whose events carry their
            # own task ids, linked back via the split context.
            wanted = {criteria["taskId"]}
            for run in self._runs():
                split = (
                    run.context.get("split")
                    if isinstance(run.context, Mapping) else None
                )
                if isinstance(split, Mapping) and split.get("parentTaskId") == criteria["taskId"]:
                    wanted.add(run.task_id)
            views = [v for v in views if v.get("taskId") in wanted]
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

    # Drives run on a bounded pool of background worker threads: a
    # step can sit in a model call for minutes, and driving on the
    # request thread froze the whole API — the dashboard could not
    # even load its lists until the call returned. The pool bound
    # (execution.maxConcurrentRuns) also bounds how many runs can be
    # inside model calls at once. The stores keep one connection per
    # thread, so request threads and drive threads never share a
    # connection object. Workers are daemon threads; shutdown()
    # stops them cleanly.
    def _drive_in_background(self, run_id: str) -> None:
        """Queue a drive for a run (coalesced per run, pool-bounded)."""
        with self._drive_condition:
            if run_id in self._drive_active or self._drive_stopped:
                return
            self._drive_active.add(run_id)
            self._drive_queue.append(run_id)
            self._ensure_drive_workers_locked()
            self._drive_condition.notify_all()

    def _ensure_drive_workers_locked(self) -> None:
        while len(self._drive_workers) < self._max_concurrent_runs:
            worker = threading.Thread(
                target=self._drive_pool_loop,
                name=f"asf-drive-pool-{len(self._drive_workers)}",
                daemon=True,
            )
            self._drive_workers.append(worker)
            # Start under the lock, like the old per-run threads, so
            # no waiter can observe a worker that has not started.
            worker.start()

    def _drive_pool_loop(self) -> None:
        while True:
            with self._drive_condition:
                while not self._drive_queue and not self._drive_stopped:
                    self._drive_condition.wait()
                if not self._drive_queue:
                    return  # stopped and drained
                run_id = self._drive_queue.popleft()
            try:
                self._drive_worker(run_id)
            except Exception:
                # _drive_worker is expected to contain drive errors;
                # a worker must never die and shrink the pool silently.
                logger.exception(
                    "Drive worker failed unexpectedly for run %s", run_id,
                )

    def _drive_worker(self, run_id: str) -> None:
        try:
            self._drive(run_id)
        finally:
            with self._drive_condition:
                self._drive_active.discard(run_id)
                self._drive_condition.notify_all()
            # A cancel requested just as the drive parked (e.g. the run
            # reached an approval gate in the same moment) must not be
            # lost with the drive: nobody is dispatching now, so the
            # cancellation can be applied directly.
            self._apply_requested_cancel(run_id)
            # If this run was a split part that just completed, its
            # completion is what starts the next part.
            self._advance_split_chain(run_id)

    def _wait_for_drive(self, run_id: str, timeout: float | None = None) -> None:
        """Wait until no drive for ``run_id`` is queued or running."""
        with self._drive_condition:
            self._drive_condition.wait_for(
                lambda: run_id not in self._drive_active, timeout=timeout,
            )

    def wait_for_drives(self, timeout: float | None = None) -> None:
        """Block until every queued/running drive finishes."""
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._drive_condition:
            while self._drive_active:
                remaining = (
                    None if deadline is None
                    else max(0.0, deadline - time.monotonic())
                )
                if remaining is not None and remaining <= 0:
                    return
                self._drive_condition.wait(timeout=remaining)

    def shutdown(self) -> None:
        """Stops the retry scheduler and the drive pool (clean exit)."""
        self.stop_scheduler()
        with self._drive_condition:
            self._drive_stopped = True
            self._drive_condition.notify_all()
            workers = list(self._drive_workers)
        for worker in workers:
            worker.join(timeout=5)

    def _flush_observations_quietly(self, run_id: str) -> None:
        try:
            self._engine.flush_observations(run_id)
        except (RuntimeError, ValueError):
            # RuntimeError: nothing to deliver to. ValueError: another
            # thread is dispatching this run right now and the engine
            # will not flush mid-dispatch. At-least-once delivery; a
            # later flush retries.
            pass

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
            except ConcurrentModificationError:
                # Another writer owns this run now (a racing drive, a
                # manual tick, a second process). Losing the claim is
                # a normal outcome, not a run failure: stop this drive
                # and let the owner (or a later drive) carry the run.
                logger.warning(
                    "Drive for run %s stopped: the run was claimed by"
                    " another writer",
                    run_id,
                )
                break
            except Exception:
                logger.exception(
                    "Drive for run %s stopped on an unexpected error",
                    run_id,
                )
                break
            if self._apply_requested_cancel(run_id):
                break
            # Publish the step's events (its STEP_STARTED line and the
            # agent's result events) now, not only when the whole drive
            # parks: SSE subscribers see the run's log grow step by step.
            self._flush_observations_quietly(run_id)
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
        self._sync_retry_schedule(run_id)
        self._notify_run_terminal(run_id)

    def _notify_run_terminal(self, run_id: str) -> None:
        """Fires the assembly's terminal hook when the run is finished.

        Idempotent on the receiver's side: drives can observe the
        same terminal run more than once (e.g. a startup re-drive of
        an already finished run), and the hook must tolerate that.
        """
        if self._on_run_terminal is None:
            return
        try:
            run = self._engine.get(run_id)
        except Exception:
            return
        if run.state.stage not in _TERMINAL_STAGES:
            return
        try:
            self._on_run_terminal(run.id, run.project_id, run.state.stage)
        except Exception:
            logger.exception(
                "Terminal hook failed for run %s (stage %s)",
                run_id, run.state.stage,
            )

    def _scheduler_clock(self) -> datetime:
        """Clock for the retry scheduler: the service's injected
        clock, else the engine's, else (stub assemblies only) UTC now."""
        clock = self._clock or getattr(self._engine, "_clock", None)
        if clock is not None:
            return clock()
        return datetime.now(timezone.utc)

    def _sync_retry_schedule(self, run_id: str) -> None:
        """Registers a parked run's retry_at with the scheduler.

        Called when a drive parks: if the run is waiting out a retry
        backoff, the scheduler will drive it again when the backoff
        expires — no manual tick needed. A run without a pending
        retry is unregistered (its schedule, if any, is stale).
        """
        try:
            run = self._engine.get(run_id)
        except Exception:
            return
        if run.retry_at is not None:
            self._scheduler.register(run_id, run.retry_at)
        else:
            self._scheduler.unregister(run_id)

    def stop_scheduler(self) -> None:
        """Stops the retry scheduler thread (tests/shutdown)."""
        self._scheduler.stop()

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
            if run.retry_at is not None:
                # Parked on a retry backoff when the backend stopped:
                # the scheduler drives it when the backoff expires
                # (a retry_at already in the past fires at once).
                self._scheduler.register(run.id, run.retry_at)
            if self._workflow_status(run) == "RUNNING":
                self._drive_in_background(run.id)
        # A split part that completed just before the previous backend
        # stopped may never have started its successor; the chain
        # state lives in the completed run's context, so re-checking
        # every completed split part here restarts any stalled chain.
        for run in self._runs():
            if run.state.stage == "COMPLETED":
                self._advance_split_chain(run.id)

    @staticmethod
    def _requirement_text(inputs: Mapping[str, Any] | None) -> str | None:
        if not isinstance(inputs, Mapping):
            return None
        spec = inputs.get("spec")
        if not isinstance(spec, Mapping):
            return None
        requirement = spec.get("requirement")
        return requirement if isinstance(requirement, str) else None

    def _validated_skip_approvals(self, value: Any) -> list[str]:
        """Normalize the create-task approval-skip list.

        Only steps that actually have an approval gate may be named;
        anything else is a client error worth failing loudly on (the
        API maps it to 422) rather than a silently ignored checkbox.
        """
        if not isinstance(value, list) or any(
            not isinstance(item, str) or not item for item in value
        ):
            raise ValueError("skipApprovals must be a list of approval step ids")
        definition = self._definition()
        valid = (
            {step.id for step in definition.steps if step.requires_approval}
            if definition is not None
            else set(value)
        )
        unknown = sorted({item for item in value if item not in valid})
        if unknown:
            raise ValueError(
                "skipApprovals names steps without an approval gate: "
                + ", ".join(unknown)
                + f" (approval steps: {', '.join(sorted(valid))})"
            )
        return list(dict.fromkeys(value))

    @staticmethod
    def _skip_approvals_of(run: WorkflowExecution) -> list[str]:
        raw = run.context.get("skipApprovals")
        if isinstance(raw, list):
            return [item for item in raw if isinstance(item, str)]
        return []

    @staticmethod
    def _requirement_tier(inputs: Mapping[str, Any] | None) -> str | None:
        """Classify a run from its requirement: "complex" or None.

        Deterministic and free (no model call): the requirement's
        length is the signal — it predicts the size of every document
        and changeset the run will produce. A caller-provided tier in
        the run context always wins over this classification.
        """
        if not isinstance(inputs, Mapping):
            return None
        spec = inputs.get("spec")
        if not isinstance(spec, Mapping):
            return None
        requirement = spec.get("requirement")
        if isinstance(requirement, str) and len(requirement) > COMPLEX_REQUIREMENT_CHARS:
            return "complex"
        return None

    def start_run(
        self,
        task_id: str,
        project_id: str,
        inputs: Mapping[str, Any] | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> WorkflowExecution:
        # Automatic splitting first: an oversized requirement is
        # decomposed into sub-tasks whose runs execute in sequence
        # under this task as parent. Child runs (context carries
        # "split") and ordinary requirements start directly; every
        # actual start classifies the run's complexity tier (see
        # _start_run_once).
        requirement = self._requirement_text(inputs)
        if (
            self._decomposer is not None
            and not (isinstance(context, Mapping) and "split" in context)
            and requirement is not None
            and len(requirement) > SPLIT_REQUIREMENT_CHARS
        ):
            return self._start_split_run(
                task_id, project_id, inputs, context, requirement,
            )
        return self._start_run_once(task_id, project_id, inputs, context)

    def _start_run_once(
        self,
        task_id: str,
        project_id: str,
        inputs: Mapping[str, Any] | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> WorkflowExecution:
        # Automatic model routing: classify the run from its
        # requirement and record the tier in its context; a
        # caller-provided tier wins. Split parts start here too, so
        # an oversized part is classified on its own text.
        merged_context = dict(context or {})
        if merged_context.get("skipApprovals") is not None:
            merged_context["skipApprovals"] = self._validated_skip_approvals(
                merged_context["skipApprovals"],
            )
        tier = self._requirement_tier(inputs)
        if tier is not None:
            merged_context.setdefault("modelTier", tier)
        run = self._engine.start(
            task_id=task_id, project_id=project_id, inputs=inputs,
            context=merged_context,
        )
        self.track(run.id)
        self._drive_in_background(run.id)
        return self._engine.get(run.id)

    def _start_split_run(
        self,
        task_id: str,
        project_id: str,
        inputs: Mapping[str, Any] | None,
        context: Mapping[str, Any] | None,
        requirement: str,
    ) -> WorkflowExecution:
        """Decompose an oversized requirement and start its first part.

        The remaining parts travel in the first part's run context
        (split.queue); each part that completes starts the next (see
        _advance_split_chain), so the chain needs no separate store
        and survives restarts, Run again and Resume.
        """
        base_context = dict(context or {})
        title = base_context.get("title")
        if not isinstance(title, str) or not title:
            title = task_id
        try:
            plan = self._decomposer.split(title=title, requirement=requirement)
        except Exception as error:
            # Never make a big task unstartable: run it whole and
            # surface the failure on the run itself.
            base_context["splitError"] = f"{type(error).__name__}: {error}"[:300]
            return self._start_run_once(task_id, project_id, inputs, base_context)
        parts = list(plan.parts)
        queue = [
            {
                "taskId": f"{task_id}-part-{index}",
                "title": part.title,
                "requirement": plan.full_requirement(part),
            }
            for index, part in enumerate(parts, start=1)
        ]
        first = queue.pop(0)
        child_context = {
            **base_context,
            "title": first["title"],
            "split": {
                "parentTaskId": task_id,
                "title": title,
                "index": 1,
                "total": len(parts),
                "batch": uuid.uuid4().hex,
                "queue": queue,
            },
        }
        spec = inputs.get("spec") if isinstance(inputs, Mapping) else None
        child_inputs = {
            **dict(inputs or {}),
            "spec": {
                **(dict(spec) if isinstance(spec, Mapping) else {}),
                "requirement": first["requirement"],
            },
        }
        return self._start_run_once(
            str(first["taskId"]), project_id, child_inputs, child_context,
        )

    def _advance_split_chain(self, run_id: str) -> None:
        """Start the next part of a split task when a part completes.

        Called when a run's drive settles and at startup. Only a
        COMPLETED part advances the chain — a failed or cancelled
        part stops it, and a human continuing that part (Run again /
        Resume, both of which preserve the split context) resumes
        the chain when the part completes. Best-effort like the
        drive itself: a start failure is retried at the next settle
        or startup, never raised into the drive worker.
        """
        try:
            run = self._engine.get(run_id)
        except Exception:
            return
        if run.state.stage != "COMPLETED":
            return
        split = run.context.get("split") if isinstance(run.context, Mapping) else None
        if not isinstance(split, Mapping):
            return
        queue = split.get("queue")
        if not isinstance(queue, list) or not queue:
            return
        nxt = queue[0]
        if not isinstance(nxt, Mapping) or not nxt.get("taskId"):
            return
        batch = split.get("batch")
        already = any(
            other.task_id == nxt["taskId"]
            and isinstance(other.context, Mapping)
            and isinstance(other.context.get("split"), Mapping)
            and other.context["split"].get("batch") == batch
            for other in self._runs()
        )
        if already:
            return
        index = split.get("index")
        child_context = {
            key: value for key, value in run.context.items() if key != "split"
        }
        child_context["title"] = nxt.get("title") or str(nxt["taskId"])
        child_context["split"] = {
            "parentTaskId": split.get("parentTaskId"),
            "title": split.get("title"),
            "index": index + 1 if isinstance(index, int) else None,
            "total": split.get("total"),
            "batch": batch,
            "queue": queue[1:],
        }
        spec = run.inputs.get("spec") if isinstance(run.inputs, Mapping) else None
        child_inputs = {
            **dict(run.inputs or {}),
            "spec": {
                **(dict(spec) if isinstance(spec, Mapping) else {}),
                "requirement": nxt.get("requirement") or "",
            },
        }
        try:
            self._start_run_once(
                str(nxt["taskId"]), run.project_id, child_inputs, child_context,
            )
        except Exception:
            pass

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
            driving = run_id in self._drive_active
            if driving:
                self._cancel_requested.add(run_id)
            else:
                self._cancel_requested.discard(run_id)
        if driving:
            return self.get_workflow(run_id)
        self._engine.cancel(run_id)
        self._notify_run_terminal(run_id)
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
        self._notify_run_terminal(run_id)
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
            # "split" rides along so a retried split part still
            # advances its chain when it completes.
            for key in ("title", "priority", "workflowType", "split")
            if isinstance(run.context, Mapping) and run.context.get(key) is not None
        }
        # The task's approval skips are part of how it was created:
        # running it again keeps the same gates skipped.
        if isinstance(run.context, Mapping):
            skip = run.context.get("skipApprovals")
            if isinstance(skip, list):
                context["skipApprovals"] = [
                    item for item in skip if isinstance(item, str)
                ]
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
