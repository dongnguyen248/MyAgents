"""FactoryService queries — read views and listings.

``QueriesMixin`` carries these methods of ``FactoryService`` (a pure split
of the former single service.py; no behavior change). The facade in the
package ``__init__`` combines the mixins; attribute and cross-group method
declarations below describe the state the facade's ``__init__`` establishes
and the sibling parts provide — declarations only, never assignments.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from typing import Any

from asf.agents._shared.security import redact_text
from asf.agents._shared.skills import agent_skill_ids
from asf.api.service import (
    _AGENT_STATUS_MAP,
    _APPROVAL_STEP_IDS,
    _APPROVAL_TYPES,
    _DASHBOARD_STEP_IDS,
    _EMPTY_OVERVIEW,
    _EPOCH,
    _PRIORITIES,
    _RESULT_STATUS_MAP,
    _STEP_ID_BY_STAGE,
    _STEP_ID_BY_STEP_ID,
    _TASK_STATUSES,
    _TERMINAL_STAGES,
    _WORKFLOW_TYPES,
    _ZERO_AGENT_METRICS,
    MetricsProtocol,
    _camelize,
    _iso,
)
from asf.api.service.review_state import review_status
from asf.approval.errors import ApprovalError
from asf.contracts.models import ActivityEvent
from asf.orchestrator.code_loop import ESCALATED_STAGE, FIX_STAGE, FIX_STEP, REWORK_STAGE
from asf.orchestrator.engine import Orchestrator
from asf.orchestrator.execution import WorkflowExecution
from asf.workflow.definition import WorkflowDefinition, WorkflowStepDef

_LOOP_STAGES = {FIX_STAGE, REWORK_STAGE, ESCALATED_STAGE}


class QueriesMixin:
    _engine: Orchestrator
    _metrics: MetricsProtocol | None
    _projects: dict[str, dict[str, Any]]
    _agent_id_for_type: Callable[[str | None], str | None]
    _definition: Callable[..., WorkflowDefinition | None]
    _hosting_token_view: Callable[[str], dict[str, Any]]
    _metadata: Callable[[str], Any | None]
    _metadata_list: Callable[[], list[Any]]
    _now: Callable[[], datetime | None]
    _runs: Callable[[], list[WorkflowExecution]]
    _stall_seconds: float
    _drive_active: set[str]
    _driver_info: dict[str, dict[str, Any]]
    _skip_approvals_of: Callable[[WorkflowExecution], list[str]]
    _stage_kind: Callable[[WorkflowExecution, str], str | None]
    _step_for_stage: Callable[[WorkflowExecution, str], WorkflowStepDef | None]
    _workspace_view: Callable[[str, str], dict[str, Any] | None] | None

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
            (run, result)
            for run in runs
            for result in run.results
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
                config.get("skills") or agent_skill_ids(str(metadata.type)) or metadata.capabilities
            ),
            "tools": list(config.get("tools") or []),
            "allowedProjectIds": list(config.get("allowedProjectIds") or self._projects.keys()),
            "maxConcurrentTasks": int(config.get("maxConcurrentTasks", 1)),
            "timeoutSeconds": int(config.get("timeoutSeconds", 1800)),
            "retryPolicy": {
                "maxRetries": int(retry.get("maxRetries", retry.get("maxAttempts", 0))),
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
                entries.append(
                    {
                        "taskId": run.task_id,
                        "projectId": run.project_id,
                        "title": run.task_id,
                        "status": _RESULT_STATUS_MAP.get(str(result.status), "Running"),
                        "startedAt": _iso(run.started_at),
                        "durationSec": float(result.metrics.duration_seconds),
                    }
                )
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
            view["durationSec"] = max(0.0, (run.updated_at - run.started_at).total_seconds())
        return view

    def list_tasks(
        self,
        filter: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        criteria: dict[str, Any] = {**(filter or {}), **kwargs}
        latest: dict[str, WorkflowExecution] = {}
        for run in sorted(self._runs(), key=lambda item: item.updated_at):
            latest[run.task_id] = run
        views = [self._task_view(run) for run in latest.values()]
        views.extend(
            view
            for view in self._split_parent_views(latest)
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
                views = [v for v in views if datetime.fromisoformat(v["createdAt"]) >= cutoff]
        views = sorted(views, key=lambda view: view["updatedAt"], reverse=True)
        return self._group_split_parts(views)

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
        self,
        latest: Mapping[str, WorkflowExecution],
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
                (run for run in reversed(children) if run.state.stage not in _TERMINAL_STAGES),
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
            views.append(
                {
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
                }
            )
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
            step is not None
            and step.requires_approval
            and run.state.stage == f"{step.stage}_REVIEW"
        )

    def _workflow_status(self, run: WorkflowExecution) -> str:
        try:
            raw = str(self._engine.workflow_run(run.id)["status"])
        except Exception:
            raw = "COMPLETED" if run.state.stage == "COMPLETED" else "RUNNING"
        if raw in _TERMINAL_STAGES:
            return raw
        if run.paused:
            return "PAUSED"
        if self._is_review_stage(run):
            return review_status(run, self._step_for_stage(run, run.state.stage))
        # The engine's coarse status calls both of these "WAITING",
        # which the old mapping flattened to RUNNING — an escalated
        # run looked identical to a healthy one. They are distinct
        # operator states and nothing should tick them pointlessly.
        if run.state.stage == ESCALATED_STAGE:
            return "ESCALATED"
        if run.retry_at is not None:
            return "WAITING_RETRY"
        return "RUNNING"

    def _fix_budget(self, run: WorkflowExecution) -> dict[str, int]:
        """Fix attempts used vs the code loop's per-item budget."""
        used = int(run.state.revisions.get(FIX_STEP, 0))
        budget = used
        graph = getattr(self._engine, "_graph", None)
        if graph is not None:
            budget = int(graph.max_revisions.get(FIX_STEP, used))
        return {"used": used, "max": budget}

    def _service_now(self, run: WorkflowExecution) -> datetime:
        now = self._now()
        return now if now is not None else run.updated_at

    def _is_stalled(self, run: WorkflowExecution, status: str) -> bool:
        """A RUNNING run nobody is moving: a step in flight past the
        watchdog limit, or no step in flight, no drive alive and no
        change for a minute (an orphan the adoption loop has not
        picked up yet, or one it gave up on)."""
        if status != "RUNNING":
            return False
        age = (self._service_now(run) - run.updated_at).total_seconds()
        if run.in_flight is not None:
            return age > self._stall_seconds
        return run.id not in self._drive_active and age > 60

    def _waiting(self, run: WorkflowExecution, status: str) -> dict[str, Any]:
        """What the run is waiting for, in operator terms.

        Always present on the workflow view: ``kind`` is NONE for a
        terminal run, otherwise exactly one of APPROVAL, ESCALATED,
        RETRY_WAIT, STEP_RUNNING or STALLED, with the moment the
        wait began, a human reason, the fix budget when relevant
        and the actions an operator can take from here.
        """
        waiting: dict[str, Any] = {
            "kind": "NONE",
            "since": _iso(run.updated_at),
            "reason": None,
            "retryAt": None,
            "budget": None,
            "suggestedActions": [],
        }
        if status in _TERMINAL_STAGES:
            return waiting
        if status == "PAUSED":
            waiting["kind"] = "PAUSED"
            waiting["reason"] = "Paused by operator — no step will start until continued"
            waiting["suggestedActions"] = ["continue", "cancel"]
            paused_event = next(
                (
                    obs.event
                    for obs in reversed(run.observations)
                    if obs.event is not None and obs.event.event_type == "RUN_PAUSED"
                ),
                None,
            )
            if paused_event is not None:
                waiting["since"] = _iso(paused_event.timestamp)
            return waiting
        if status == "WAITING_APPROVAL":
            waiting["kind"] = "APPROVAL"
            waiting["suggestedActions"] = ["approve", "reject", "cancel"]
            try:
                pending = self._engine.pending_approval(run.id)
            except Exception:
                pending = None
            if pending is not None:
                waiting["since"] = _iso(pending.requested_at)
                waiting["reason"] = (
                    f"Waiting for approval of {pending.type} "
                    f"(reviewers: {', '.join(pending.reviewers) or 'any'})"
                )
            else:
                waiting["reason"] = "Waiting for approval"
            return waiting
        if status == "ESCALATED":
            budget = self._fix_budget(run)
            waiting["kind"] = "ESCALATED"
            waiting["budget"] = budget
            waiting["suggestedActions"] = ["resume", "cancel"]
            waiting["reason"] = (
                f"Escalated — fix budget used ({budget['used']}/{budget['max']}), needs operator"
            )
            escalated = next(
                (
                    obs.event
                    for obs in reversed(run.observations)
                    if obs.event is not None and obs.event.event_type == "WORKFLOW_ESCALATED"
                ),
                None,
            )
            if escalated is not None:
                waiting["since"] = _iso(escalated.timestamp)
                waiting["reason"] = escalated.message
            return waiting
        if status == "WAITING_RETRY":
            waiting["kind"] = "RETRY_WAIT"
            waiting["retryAt"] = _iso(run.retry_at)
            waiting["reason"] = "Step failed; waiting to retry"
            waiting["suggestedActions"] = ["cancel"]
            return waiting
        if self._is_stalled(run, status):
            waiting["kind"] = "STALLED"
            waiting["suggestedActions"] = ["adopt", "cancel"]
            waiting["reason"] = (
                "Step in flight longer than the watchdog limit"
                if run.in_flight is not None
                else "No drive is advancing this run"
            )
            return waiting
        # RUNNING and none of the waits above: a step is in flight
        # or the run is between ticks of an active drive.
        waiting["kind"] = "STEP_RUNNING"
        waiting["suggestedActions"] = ["cancel"]
        return waiting

    def _driver_view(self, run_id: str) -> dict[str, Any]:
        info = self._driver_info.get(run_id, {})
        return {
            "alive": run_id in self._drive_active,
            "lastTickAt": info.get("lastTickAt"),
            "lastStopReason": info.get("lastStopReason"),
        }

    def _workspace_info(self, run: WorkflowExecution) -> dict[str, Any] | None:
        """The run's local-workspace block for the workflow view.

        The assembly hook reports the live state (mode, folder, files
        written, journal state). A finished direct-mode run's journal
        is discarded or closed, so the terminal WORKSPACE_JOURNAL
        event the hook recorded fills in the final journal state and
        file list when the live view no longer has them.
        """
        if self._workspace_view is None:
            return None
        try:
            info = self._workspace_view(run.project_id, run.id)
        except Exception:
            return None
        if info is None:
            return None
        info = dict(info)
        if info.get("journalState") is None:
            event = self._journal_event(run)
            if event is not None:
                info["journalState"] = event.get("journalState")
                if not info.get("filesWritten"):
                    info["filesWritten"] = event.get("filesWritten") or []
                if event.get("conflicts"):
                    info["conflicts"] = event["conflicts"]
        return info

    @staticmethod
    def _journal_event(run: WorkflowExecution) -> dict[str, Any] | None:
        for observation in reversed(run.observations):
            event = observation.event
            if event is not None and event.event_type == "WORKSPACE_JOURNAL":
                return dict(event.metadata)
        return None

    @staticmethod
    def _trail_stages(run: WorkflowExecution) -> list[str]:
        """The run's stage trail, newest first, terminal stages removed."""
        stages: list[str] = []
        for observation in reversed(run.observations):
            event = observation.event
            if event is None or event.event_type not in (
                "WORKFLOW_STARTED",
                "WORKFLOW_STAGE_CHANGED",
            ):
                continue
            stage = event.metadata.get("stage")
            if isinstance(stage, str) and stage not in (
                "FAILED",
                "COMPLETED",
                "CANCELLED",
            ):
                stages.append(stage)
        return stages

    @staticmethod
    def _stage_before_failure(run: WorkflowExecution) -> str | None:
        """The stage a FAILED/CANCELLED run was in just before it ended,
        from its event trail."""
        stages = QueriesMixin._trail_stages(run)
        return stages[0] if stages else None

    def _step_states(
        self,
        run: WorkflowExecution,
        definition: WorkflowDefinition,
        status: str,
    ) -> list[dict[str, Any]]:
        sequence = ["NEW"]
        for step in definition.steps:
            sequence.extend(step.generated_stages())
        sequence.extend(["COMPLETED", "FAILED", "CANCELLED"])
        stage = run.state.stage
        current_index = sequence.index(stage) if stage in sequence else None
        # Code-loop stages are injected by the loop graph and appear
        # in NO step's generated stages, so the index lookup above
        # fails for a run inside the loop and (for a live run) every
        # step fell back to pending. Anchor such a run just past the
        # testing step — exactly where the loop sits — so the steps
        # before the loop resolve by the usual index rules, then add
        # the loop's own synthetic step below.
        loop_stage: str | None = stage if stage in _LOOP_STAGES else None
        if status == "FAILED":
            before = self._stage_before_failure(run)
            if before in _LOOP_STAGES:
                loop_stage = before
        if loop_stage is not None and status not in ("COMPLETED", "CANCELLED", "FAILED"):
            testing_step = next(
                (
                    step
                    for step in definition.steps
                    if (_STEP_ID_BY_STEP_ID.get(step.id) or _STEP_ID_BY_STAGE.get(step.stage))
                    == "testing"
                ),
                None,
            )
            if testing_step is not None:
                testing_stages = testing_step.generated_stages()
                if testing_stages and testing_stages[-1] in sequence:
                    current_index = sequence.index(testing_stages[-1])
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
                if terminal_from_index is None and stage_before in _LOOP_STAGES:
                    approved_indexes = [
                        sequence.index(f"{step.stage}_APPROVED")
                        for step in definition.steps
                        if step.requires_approval and f"{step.stage}_APPROVED" in sequence
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
                    mapped = _STEP_ID_BY_STEP_ID.get(candidate.id) or _STEP_ID_BY_STAGE.get(
                        candidate.stage
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
                    "done" if step.produces and set(step.produces) <= produced else "cancelled"
                )
            elif current_index is not None:
                main_state = "done" if max(indexes) < current_index else "pending"
            else:
                main_state = "pending"
            steps.append({"id": main_id, "label": step.name, "state": main_state})
            approval_id = _APPROVAL_STEP_IDS.get(main_id)
            if step.requires_approval and approval_id is not None:
                approval_state = self._approval_step_state(
                    step,
                    stage,
                    current_index,
                    sequence,
                    status,
                    terminal_from_index,
                )
                if approval_state == "done" and main_id in skip_ids:
                    # The run passed this gate because the task asked
                    # to skip it — say so instead of implying a human
                    # approved it.
                    approval_state = "skipped"
                steps.append(
                    {
                        "id": approval_id,
                        "label": f"{step.name} approval",
                        "state": approval_state,
                    }
                )
        if loop_stage is not None and status != "CANCELLED":
            budget = self._fix_budget(run)
            if status == "FAILED":
                fix_state = "failed"
            elif loop_stage == FIX_STAGE:
                fix_state = "active"
            elif loop_stage == REWORK_STAGE:
                fix_state = "rejected"
            else:
                fix_state = "escalated"
            if status != "FAILED":
                # Review delivered the verdict that opened this cycle
                # (the index rules already mark it done); testing
                # shows whether this cycle has produced a report.
                for entry in steps:
                    if entry["id"] == "testing":
                        entry["state"] = "done" if "TEST_REPORT" in run.artifacts else "pending"
            fix_step = {
                "id": "fix",
                "label": f"Fix code · fix {budget['used']}/{budget['max']}",
                "state": fix_state,
            }
            testing_at = next(
                (i for i, entry in enumerate(steps) if entry["id"] == "testing"),
                None,
            )
            if testing_at is None:
                steps.append(fix_step)
            else:
                steps.insert(testing_at + 1, fix_step)
        return steps

    @staticmethod
    def _approval_step_state(
        step: WorkflowStepDef,
        stage: str,
        current_index: int | None,
        sequence: list[str],
        status: str,
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
            "stage": QueriesMixin._stage_before_failure(run),
        }

    def _current_activity(
        self,
        run: WorkflowExecution,
        steps: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """What the run is doing or waiting for, for the live strip.

        Covers EVERY non-terminal state, so the strip never just
        disappears on a stuck run: a step in flight (``in_flight``
        is stamped and saved before dispatch, so a minutes-long
        model call still reports its step and start), a scheduled
        retry, an approval gate, an escalation, or a stall (same
        derivation as the view's ``waiting`` block). Terminal runs
        return None — their own cards explain those states.
        """
        if run.state.stage in _TERMINAL_STAGES:
            return None
        status = self._workflow_status(run)
        waiting = self._waiting(run, status)
        active = next((s for s in steps if s.get("state") == "active"), None)
        base: dict[str, Any] = {
            "stepId": active["id"] if active else None,
            "stepLabel": active["label"] if active else None,
            "stage": run.state.stage,
            "since": waiting["since"],
            "reason": waiting["reason"],
            "retryAt": waiting["retryAt"],
        }
        kind = waiting["kind"]
        return {**base, "kind": kind if kind != "NONE" else "STEP_RUNNING"}

    def _workflow_view(self, run: WorkflowExecution) -> dict[str, Any]:
        definition = self._definition(run)
        status = self._workflow_status(run)
        steps = self._step_states(run, definition, status) if definition else []
        split = run.context.get("split") if isinstance(run.context, Mapping) else None
        if not isinstance(split, Mapping):
            split = {}
        split_error = run.context.get("splitError") if isinstance(run.context, Mapping) else None
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
            # What the run is waiting for (approval / escalation /
            # retry / stall) and the drive's own state — the fields
            # an operator needs before deciding what to do with a
            # run that is not moving.
            "waiting": self._waiting(run, status),
            "driver": self._driver_view(run.id),
            # Local workspace of the run (direct/worktree mode, folder,
            # files written, undo-journal state) when the assembly
            # provides it and the project has a local folder.
            "workspace": self._workspace_info(run),
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

    def run_diagnostics(self, run_id: str) -> dict[str, Any] | None:
        """Everything an operator needs to answer "where is this run,
        what is it waiting for, and why did it stop" in one payload:
        stage + kind, the waiting derivation, the in-flight marker
        with its age, the retry deadline, the fix budget, the last
        20 history events, the most recent error (redacted), the
        drive's own state and the suggested next actions.
        """
        run = next((item for item in self._runs() if item.id == run_id), None)
        if run is None:
            return None
        status = self._workflow_status(run)
        waiting = self._waiting(run, status)
        now = self._service_now(run)
        events = [
            {
                "type": obs.event.event_type,
                "message": obs.event.message,
                "at": _iso(obs.event.timestamp),
                "metadata": {
                    key: redact_text(value) if isinstance(value, str) else value
                    for key, value in obs.event.metadata.items()
                },
            }
            for obs in run.observations
            if obs.event is not None
        ][-20:]
        last_error: dict[str, Any] | None = None
        if run.errors:
            error = run.errors[-1]
            last_error = {
                "code": error.code,
                "message": redact_text(error.message)[:300],
                "category": error.category,
                "retryable": error.retryable,
                "at": _iso(error.timestamp),
                "details": error.details or None,
            }
        return {
            "runId": run.id,
            "taskId": run.task_id,
            "projectId": run.project_id,
            "stage": run.state.stage,
            "stageKind": self._stage_kind(run, run.state.stage),
            "status": status,
            "waiting": waiting,
            "inFlight": (
                {
                    "token": run.in_flight,
                    "ageSeconds": max(0.0, (now - run.updated_at).total_seconds()),
                }
                if run.in_flight is not None
                else None
            ),
            "retryAt": _iso(run.retry_at) if run.retry_at is not None else None,
            "fixBudget": self._fix_budget(run),
            "revisions": dict(run.state.revisions),
            "lastEvents": events,
            "lastError": last_error,
            "driver": self._driver_view(run.id),
            "suggestedActions": waiting["suggestedActions"],
        }

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
                "activeAgents": len({result.agent_id for run in own for result in run.results}),
                "running": sum(run.state.stage not in _TERMINAL_STAGES for run in own),
                "completed": completed,
                "failed": failed,
                "successRate": completed / finished if finished else 0.0,
                "pendingApprovals": sum(self._is_review_stage(run) for run in own),
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
            projects.append(
                {
                    "id": profile["id"],
                    "name": profile["name"],
                    "repositoryProvider": profile["repositoryProvider"],
                    "repositoryUrl": profile["repositoryUrl"],
                    "repositoryPath": profile["repositoryPath"],
                    "workspaceMode": profile["workspaceMode"],
                    "keepChangesOnFailure": profile["keepChangesOnFailure"],
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
                }
            )
        return projects

    # ------------------------------------------------------------------
    # hosting tokens (per project; write-only, never part of the profile)
    # ------------------------------------------------------------------

    def _project_view(self, project_id: str) -> dict[str, Any]:
        return next(view for view in self.list_projects() if view["id"] == project_id)

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
            step = (
                next(
                    (item for item in definition.steps if item.id == step_id),
                    None,
                )
                if definition is not None
                else None
            )
            requested_by = (
                self._agent_id_for_type(step.agent_type) if step is not None else None
            ) or request.requested_by
            artifact_name = request.artifact_id
        requested_at = getattr(request, "requested_at", None) or getattr(
            request,
            "created_at",
            None,
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

    @staticmethod
    def _activity_view(event: ActivityEvent) -> dict[str, Any]:
        event_type = event.event_type or ""
        metadata = event.metadata or {}
        if event_type.startswith("APPROVAL"):
            source_kind = "approval"
        elif str(metadata.get("source", "")).lower() in {
            "integration",
            "ci",
            "gitlab",
            "github",
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
        # Operator-facing event metadata: why an agent failed
        # (AGENT_FAILED/AGENT_REJECTED) or why a drive stopped
        # (DRIVE_STOPPED). Other metadata stays server-side.
        detail = {
            key: metadata[key]
            for key in (
                "errorCode",
                "errorCategory",
                "retryable",
                "errorMessage",
                "reason",
                "errorType",
            )
            if key in metadata
        }
        if detail:
            view["metadata"] = detail
        return view

    def list_activity(
        self,
        filter: Mapping[str, Any] | None = None,
        **kwargs: Any,
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
            events.values(),
            key=lambda event: event.timestamp,
            reverse=True,
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
                split = run.context.get("split") if isinstance(run.context, Mapping) else None
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
