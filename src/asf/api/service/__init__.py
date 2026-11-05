"""Framework-free dashboard service over the orchestrator.

``FactoryService`` maps the orchestrator's contract-shaped views onto the
exact JSON shapes the dashboard frontend consumes (see
``apps/dashboard/src/types/*.ts``). It contains no web-framework imports so it
can be unit-tested (and reused) without FastAPI installed.

The implementation is split by concern into submodules of this
package — ``queries`` (views/lists), ``commands`` (mutations) and
``driver`` (background drives/scheduler) — with ``FactoryService``
below as the facade combining them; shared constants and helpers
live here, above the mixin imports.

Lossy points of the mapping are documented in ``src/asf/api/README.md``.
Time is never read from the system clock here: timestamps come from the
runs themselves or from the injected ``clock`` callable.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from asf.api.hosting_tokens import HostingTokens
from asf.api.scheduler import RunScheduler
from asf.configuration.project import ProjectProfile
from asf.contracts.models import ActivityEvent
from asf.orchestrator.engine import Orchestrator
from asf.orchestrator.execution import WorkflowExecution
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

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

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
    "SPEC_DRAFT",
    "SPEC_REVIEW",
    "SPEC_REJECTED",
    "SPEC_APPROVED",
    "PLAN_DRAFT",
    "PLAN_REVIEW",
    "PLAN_REJECTED",
    "PLAN_APPROVED",
    "TASK_DRAFT",
    "TASK_REVIEW",
    "TASK_REJECTED",
    "TASK_APPROVED",
    "IMPLEMENTING",
    "CODE_REVIEW",
    "TESTING",
    "CI",
    "READY_TO_MERGE",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
}

_WORKFLOW_TYPES = {"feature-development", "bug-fix", "refactoring"}
_PRIORITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
_APPROVAL_TYPES = {"SPEC", "PLAN", "TASK", "CODE_REVIEW", "DEPLOYMENT"}
_TERMINAL_STAGES = {"COMPLETED", "FAILED", "CANCELLED"}

_DASHBOARD_STEP_IDS = {
    "spec",
    "plan",
    "task",
    "implementation",
    "code_review",
    "testing",
    "ci",
    "merge",
}
_STEP_ID_BY_STEP_ID = {
    "spec": "spec",
    "plan": "plan",
    "task": "task",
    "implement": "implementation",
    "review": "code_review",
    "test": "testing",
    "ci": "ci",
    "merge": "merge",
}
_STEP_ID_BY_STAGE = {
    "SPEC": "spec",
    "PLAN": "plan",
    "TASK": "task",
    "IMPLEMENTING": "implementation",
    "CODE_REVIEW": "code_review",
    "TESTING": "testing",
    "CI": "ci",
    "READY_TO_MERGE": "merge",
}
_APPROVAL_STEP_IDS = {"spec": "spec_approval", "plan": "plan_approval", "task": "task_approval"}

_ZERO_AGENT_METRICS: dict[str, Any] = {
    "total": 0,
    "completed": 0,
    "running": 0,
    "failed": 0,
    "cancelled": 0,
    "successRate": 0.0,
    "avgDurationSec": 0.0,
    "avgRevisions": 0.0,
    "humanApprovalRate": 0.0,
    "testPassRate": 0.0,
    "ciPassRate": 0.0,
}

_EMPTY_OVERVIEW: dict[str, Any] = {
    "daily": [],
    "human": {
        "approvalRate": 0.0,
        "rejectionRate": 0.0,
        "avgRevisions": 0.0,
        "avgApprovalMinutes": 0.0,
        "daily": [],
    },
    "quality": {
        "codeReviewRejectionRate": 0.0,
        "testPassRate": 0.0,
        "ciPassRate": 0.0,
        "reworkRate": 0.0,
        "daily": [],
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


def _parse_iso(value: Any) -> datetime | None:
    """Parses an ISO-8601 timestamp (accepting a trailing 'Z')."""
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


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
            not isinstance(argv, list)
            or not argv
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


# The mixins import the shared names defined above from this
# package, so they can only be imported after those definitions.
from asf.api.service.commands import CommandsMixin  # noqa: E402
from asf.api.service.driver import DriverMixin  # noqa: E402
from asf.api.service.queries import QueriesMixin  # noqa: E402

__all__ = [
    "FactoryService",
    "MetricsProtocol",
    "ProjectConflictError",
    "ProjectExistsError",
    "ProjectNotFoundError",
]


class FactoryService(QueriesMixin, CommandsMixin, DriverMixin):
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
        stall_seconds: float = 900,
    ) -> None:
        # Watchdog: a step in flight longer than this (or a run
        # nobody is driving and nothing has touched for a minute)
        # is reported to operators as STALLED.
        self._stall_seconds = stall_seconds
        # Per-run drive bookkeeping kept in RAM for the workflow
        # view and diagnostics: when a drive last ticked the run
        # and why the most recent drive stopped.
        self._driver_info: dict[str, dict[str, Any]] = {}
        # Orphan adoption: consecutive adoption drives per run and
        # the last (stage, result-count) seen, so a run that makes
        # no progress is adopted at most _ADOPT_LIMIT times in a row.
        self._adopt_attempts: dict[str, int] = {}
        self._adopt_seen: dict[str, tuple[str, int]] = {}
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
            periodic=self._adopt_orphans,
            periodic_seconds=30,
        )
        self._projects = {
            pid: self._normalize_project(pid, profile) for pid, profile in projects.items()
        }
        self._tracked: list[str] = []
        self._store_runs: dict[str, WorkflowExecution] = {}
        self._runs_cache: list[WorkflowExecution] | None = None
        self._runs_cache_at: float = 0.0
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
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        if self._model_settings is None:
            return None
        return self._model_settings.update(payload)

    def test_model_settings(
        self,
        agent: str | None = None,
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
            channel = approval.get("channel") if isinstance(approval, Mapping) else None
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
        approval = configuration.get("approval") if isinstance(configuration, Mapping) else None
        channel = approval.get("channel") if isinstance(approval, Mapping) else None
        raw_skills = data.get("enabledSkills", data.get("enabled_skills"))
        return {
            "id": str(data.get("id", project_id)),
            "name": str(data.get("name", project_id)),
            "repositoryProvider": str(provider),
            "repositoryUrl": (
                str(repository.get("url") or "") if isinstance(repository, Mapping) else ""
            ),
            "repositoryPath": (
                str(repository.get("path") or "") if isinstance(repository, Mapping) else ""
            ),
            "testCommands": _valid_test_commands(
                configuration.get("testCommands") if isinstance(configuration, Mapping) else None
            ),
            "technologies": [str(item) for item in technologies],
            "description": str(data.get("description", "")),
            "workflow": str(data.get("workflow", "")),
            "enabledSkills": (
                [str(skill) for skill in raw_skills if isinstance(skill, str)]
                if isinstance(raw_skills, list)
                else []
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
        summaries = getattr(self._store, "list_execution_summaries", None)
        for project_id in self._projects:
            try:
                if callable(summaries):
                    # Cheap path: metadata rows only. A full payload is
                    # (re)loaded just for runs that are new or whose
                    # updated_at moved past the cached copy — the old
                    # shape deserialized EVERY run on EVERY request.
                    for summary in summaries(project_id):
                        self._refresh_store_run(summary)
                else:
                    for run in self._store.list_executions(project_id):
                        self._store_runs[run.id] = run
                        if run.id not in self._tracked:
                            self._tracked.append(run.id)
            except Exception:
                # Discovery used to swallow this silently, which made
                # a broken store look like "no runs exist".
                logger.warning(
                    "Could not discover stored runs for project %s",
                    project_id,
                    exc_info=True,
                )
                continue

    def _refresh_store_run(self, summary: Mapping[str, Any]) -> None:
        run_id = summary.get("id")
        if not isinstance(run_id, str) or not run_id:
            return
        if run_id not in self._tracked:
            self._tracked.append(run_id)
        cached = self._store_runs.get(run_id)
        if cached is not None:
            updated = _parse_iso(summary.get("updatedAt"))
            if updated is not None and updated <= cached.updated_at:
                return  # cached copy is current; skip the payload load
        try:
            self._store_runs[run_id] = self._store.get_execution(run_id)  # type: ignore[union-attr]
        except Exception:
            logger.warning(
                "Could not load stored run %s",
                run_id,
                exc_info=True,
            )

    # List endpoints poll: the dashboard asks for the run list every
    # few seconds. Assembling it costs a store discovery + an engine
    # read per run, so the assembled list is cached for a breath —
    # long enough to absorb a poll burst, short enough that a human
    # never acts on stale state. Every mutating service method and
    # every finished drive invalidates it immediately.
    _RUNS_CACHE_TTL_SECONDS = 1.5

    def _invalidate_runs_cache(self) -> None:
        self._runs_cache = None

    def _runs(self) -> list[WorkflowExecution]:
        now = time.monotonic()
        if (
            self._runs_cache is not None
            and now - self._runs_cache_at < self._RUNS_CACHE_TTL_SECONDS
        ):
            return list(self._runs_cache)
        self._discover_store_runs()
        found: dict[str, WorkflowExecution] = {}
        for run_id in self._tracked:
            try:
                found[run_id] = self._engine.get(run_id, copy=False)
            except Exception:
                if run_id in self._store_runs:
                    found[run_id] = self._store_runs[run_id]
        for run_id, run in self._store_runs.items():
            found.setdefault(run_id, run)
        result = sorted(found.values(), key=lambda run: (run.started_at, run.id))
        self._runs_cache = result
        self._runs_cache_at = now
        return list(result)

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
        self,
        run: WorkflowExecution,
        stage: str,
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
