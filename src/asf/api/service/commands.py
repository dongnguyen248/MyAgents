"""FactoryService commands — commands that change state.

``CommandsMixin`` carries these methods of ``FactoryService`` (a pure
split of the former single service.py; no behavior change).
The facade in the package ``__init__`` combines the mixins.
Attribute and cross-group method declarations below describe
the state the facade's ``__init__`` establishes and the
sibling parts provide — declarations only, never assignments.
"""

from __future__ import annotations

import contextlib
import os
import threading
import uuid
from collections.abc import Callable, Mapping
from contextlib import suppress
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from asf.api.hosting_tokens import HostingTokens
from asf.api.service import (
    _DECISIONS,
    _PROJECT_ID_PATTERN,
    _TERMINAL_STAGES,
    COMPLEX_REQUIREMENT_CHARS,
    SPLIT_REQUIREMENT_CHARS,
    MetricsProtocol,
    ProjectConflictError,
    ProjectExistsError,
    ProjectNotFoundError,
    _iso,
)
from asf.approval.errors import ApprovalError
from asf.configuration.project import ProjectProfile
from asf.configuration.yamlio import deep_merge
from asf.integrations.hosting.factory import DEFAULT_TOKEN_ENVS
from asf.orchestrator.engine import Orchestrator
from asf.orchestrator.execution import WorkflowExecution
from asf.workflow.definition import WorkflowDefinition


class CommandsMixin:
    _engine: Orchestrator
    _metrics: MetricsProtocol | None
    _reviewer: str
    _on_project_created: Callable[[ProjectProfile], None] | None
    _on_project_updated: Callable[[ProjectProfile], None] | None
    _on_project_deleted: Callable[[str], None] | None
    _hosting_tokens: HostingTokens | None
    _decomposer: Any
    _project_profiles: dict[str, dict[str, Any]]
    _projects: dict[str, dict[str, Any]]
    _drive_lock: threading.Lock
    _drive_active: set[str]
    _cancel_requested: set[str]
    _approval_view: Callable[[WorkflowExecution, Any], dict[str, Any]]
    _definition: Callable[..., WorkflowDefinition | None]
    _drive_in_background: Callable[[str], None]
    _invalidate_runs_cache: Callable[[], None]
    _normalize_project: Callable[[str, Any], dict[str, Any]]
    _notify_run_terminal: Callable[[str], None]
    _now: Callable[[], datetime | None]
    _project_view: Callable[[str], dict[str, Any]]
    _runs: Callable[[], list[WorkflowExecution]]
    _wait_for_drive: Callable[..., None]
    get_workflow: Callable[[str], dict[str, Any] | None]
    track: Callable[[str], WorkflowExecution | None]

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
        self,
        project_id: str,
        token: str | None,
        clear: bool,
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

    def update_project(
        self,
        project_id: str,
        payload: Mapping[str, Any],
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
            self._project_profiles.get(project_id, {}),
            data,
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
            run
            for run in self._runs()
            if run.project_id == project_id and run.state.stage not in _TERMINAL_STAGES
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

    def decide_approval(
        self,
        approval_id: str,
        *,
        decision: str,
        comment: str = "",
    ) -> dict[str, Any]:
        self._invalidate_runs_cache()
        if decision not in (*_DECISIONS, "COMMENT"):
            raise ValueError(f"Unknown approval decision: {decision}")
        run = next(
            (item for item in self._runs() if item.approval_id == approval_id),
            None,
        )
        if run is None:
            raise ApprovalError(
                "NOT_FOUND",
                "Approval is not pending for any known run",
            )
        request = self._engine.pending_approval(run.id)
        view = self._approval_view(run, request)
        if decision == "COMMENT":
            if comment:
                view["comments"].append(
                    {
                        "author": self._reviewer,
                        "at": _iso(self._now() or run.updated_at),
                        "text": comment,
                    }
                )
            return view
        engine_decision, dashboard_status = _DECISIONS[decision]
        artifact = run.artifact_history.get(request.artifact_id)
        producing_agent = artifact.created_by if artifact is not None else None
        self._engine.decide(
            run.id,
            reviewer=self._reviewer,
            decision=engine_decision,  # type: ignore[arg-type]
            comment=comment,
            expected_approval_id=approval_id,
        )
        # Metrics are keyed by agent id (as in AgentResult.agent_id), so the
        # approval outcome must be recorded under the same id, not the type.
        self._record_approval_decision(run, producing_agent, engine_decision)
        decided_run = self._engine.get(run.id)
        # A multi-approval quorum may leave the same request still pending.
        view["status"] = "PENDING" if decided_run.approval_id == approval_id else dashboard_status
        if comment:
            view["comments"].append(
                {
                    "author": self._reviewer,
                    "at": _iso(self._now() or decided_run.updated_at),
                    "text": comment,
                }
            )
        if view["status"] != "PENDING":
            # The gate is cleared: the run continues on its own to the
            # next approval gate (or to completion) — no manual tick.
            self._drive_in_background(run.id)
        return view

    def _record_approval_decision(
        self,
        run: WorkflowExecution,
        agent_id: str | None,
        decision: str,
    ) -> None:
        if not agent_id:
            return
        if self._metrics is None or not hasattr(self._metrics, "record_approval_decision"):
            return
        record = self._metrics.record_approval_decision
        try:
            record(
                project_id=run.project_id,
                task_id=run.task_id,
                agent_id=agent_id,
                decision=decision,
                at=None,
            )
        except TypeError:
            with suppress(Exception):
                record(
                    project_id=run.project_id,
                    task_id=run.task_id,
                    agent_id=agent_id,
                    decision=decision,
                )
        except Exception:  # nosec B110
            pass

    # ------------------------------------------------------------------
    # activity
    # ------------------------------------------------------------------

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
        self._invalidate_runs_cache()
        requirement = self._requirement_text(inputs)
        if (
            self._decomposer is not None
            and not (isinstance(context, Mapping) and "split" in context)
            and requirement is not None
            and len(requirement) > SPLIT_REQUIREMENT_CHARS
        ):
            return self._start_split_run(
                task_id,
                project_id,
                inputs,
                context,
                requirement,
            )
        return self._start_run_once(task_id, project_id, inputs, context)

    def _start_run_once(
        self,
        task_id: str,
        project_id: str,
        inputs: Mapping[str, Any] | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> WorkflowExecution:
        self._invalidate_runs_cache()
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
            task_id=task_id,
            project_id=project_id,
            inputs=inputs,
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
            str(first["taskId"]),
            project_id,
            child_inputs,
            child_context,
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
        child_context = {key: value for key, value in run.context.items() if key != "split"}
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
        with contextlib.suppress(Exception):
            self._start_run_once(
                str(nxt["taskId"]),
                run.project_id,
                child_inputs,
                child_context,
            )

    def tick_run(self, run_id: str) -> dict[str, Any] | None:
        self._invalidate_runs_cache()
        # A manual tick must not race the run's background drive: wait
        # for the drive to park the run, then tick (usually a no-op).
        self._wait_for_drive(run_id)
        self._engine.tick(run_id)
        # Observation delivery is at-least-once; a retry happens later.
        with suppress(RuntimeError):
            self._engine.flush_observations(run_id)
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
        self._invalidate_runs_cache()
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
                context["skipApprovals"] = [item for item in skip if isinstance(item, str)]
        new_run = self.start_run(
            run.task_id,
            run.project_id,
            inputs=dict(run.inputs),
            context=context or None,
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
        self._invalidate_runs_cache()
        run = self._engine.resume_failed(run_id)
        self.track(run.id)
        self._drive_in_background(run.id)
        return self.get_workflow(run.id)
