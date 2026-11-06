from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, nullcontext
from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any, Literal

from asf.approval.errors import ApprovalError
from asf.approval.models import ApprovalDecision, ApprovalPolicy, ApprovalRequest, ApprovalSpec
from asf.approval.service import ApprovalService
from asf.contracts.models import ActivityEvent, AgentRequest, AgentResult, PlatformError
from asf.orchestrator.ai_review import ai_stage, dispatch_claimed
from asf.orchestrator.ai_review_apply import apply_review_result
from asf.orchestrator.budget import RunBudget, budget_exceeded_message
from asf.orchestrator.code_loop import (
    ESCALATED_STAGE,
    FIX_STAGE,
    FIX_STEP,
    REWORK_STAGE,
    CodeLoopPolicy,
    code_steps,
    loop_graph,
    ordered_task_ids,
)
from asf.orchestrator.execution import Observation, WorkflowExecution
from asf.orchestrator.ports import (
    ConcurrentModificationError,
    EventPublisher,
    ExecutionStore,
    MetricsRecorder,
)
from asf.orchestrator.registry import AgentRegistry
from asf.state_machine.graph import build_graph
from asf.state_machine.machine import InvalidTransition, RunState, allowed_triggers, apply
from asf.state_machine.status import kind_of, run_status, task_status
from asf.state_machine.triggers import StageKind, Trigger
from asf.workflow.definition import WorkflowDefinition, WorkflowStepDef

_LOOP_STAGES = {FIX_STAGE, REWORK_STAGE, ESCALATED_STAGE}


def _comparable_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """Settings as compared at load time.

    The code loop's ``max_fixes`` is masked out: it is an operator
    budget, not a structural policy — raising it in the platform
    config and restarting must not orphan every stored run (the
    supported way out of an escalation is exactly that: raise the
    budget, restart, resume). Every other field, including the
    loop's structural options, still compares strictly.
    """
    comparable = dict(settings)
    code_loop = comparable.get("codeLoop")
    if isinstance(code_loop, dict):
        comparable["codeLoop"] = {**code_loop, "max_fixes": 0}
    return comparable


class Orchestrator:
    """Synchronous, single-process dispatcher. Each tick executes at most one agent."""

    def __init__(
        self,
        definition: WorkflowDefinition,
        registry: AgentRegistry,
        *,
        clock: Callable[[], datetime],
        new_id: Callable[[], str],
        approvals: ApprovalService | None = None,
        approval_policy: ApprovalPolicy | None = None,
        store: ExecutionStore | None = None,
        code_loop: CodeLoopPolicy | None = None,
        budget: RunBudget | None = None,
        actions: Mapping[str, Callable[[AgentRequest], AgentResult]] | None = None,
        events: EventPublisher | None = None,
        metrics: MetricsRecorder | None = None,
    ) -> None:
        if store is not None:
            if approvals is not None:
                raise ValueError("Persistent executions must use the store's approval repository")
            approvals = ApprovalService(store.approvals, id_factory=new_id)
        if any(step.requires_approval for step in definition.steps):
            if approvals is None or approval_policy is None:
                raise ValueError("Approval steps require ApprovalService and ApprovalPolicy")
            if any(len(step.produces) != 1 for step in definition.steps if step.requires_approval):
                raise ValueError("Approval steps must produce exactly one artifact type")
        self._definition = definition.model_copy(deep=True)
        self._graph = build_graph(self._definition)
        self._code_loop = code_loop.model_copy(deep=True) if code_loop else None
        self._budget = budget.model_copy(deep=True) if budget else None
        if self._code_loop is not None:
            self._graph = loop_graph(self._graph, self._definition, self._code_loop)
        self._registry = registry
        self._clock = clock
        self._new_id = new_id
        self._approvals = approvals
        self._approval_policy = approval_policy.model_copy(deep=True) if approval_policy else None
        self._runs: dict[str, WorkflowExecution] = {}
        self._active: set[str] = set()
        self._store = store
        self._actions = dict(actions or {})
        self._events = events
        self._metrics = metrics

    def _settings(self) -> dict[str, Any]:
        # (see _comparable_settings for the load-time comparison)
        return {
            "approvalPolicy": (
                self._approval_policy.to_contract() if self._approval_policy else None
            ),
            "codeLoop": self._code_loop.model_dump() if self._code_loop else None,
        }

    def _load(self, run_id: str, *, for_update: bool = False) -> WorkflowExecution:
        run = (
            self._store.get_execution(run_id, for_update=for_update)
            if self._store
            else self._runs[run_id]
        )
        if run.definition != self._definition.to_contract() or (
            _comparable_settings(run.settings) != _comparable_settings(self._settings())
        ):
            raise ValueError("Stored workflow definition or execution policy differs")
        self._runs[run_id] = run
        return run

    @contextmanager
    def _edit(
        self,
        run_id: str,
        *,
        lock: bool = False,
    ) -> Iterator[WorkflowExecution]:
        with self._store.transaction() if self._store else nullcontext():
            run = self._load(run_id, for_update=lock)
            before = run.snapshot()
            try:
                yield run
                if run.state.stage != before.state.stage:
                    self._event(
                        run,
                        "WORKFLOW_COMPLETED"
                        if run.state.stage == "COMPLETED"
                        else "WORKFLOW_STAGE_CHANGED",
                        "Workflow stage changed",
                    )
                run.touch(self._now())
                if self._store:
                    self._store.save_execution(run)
            except BaseException:
                self._runs[run_id] = before
                raise

    def record_event(
        self,
        run_id: str,
        event_type: str,
        message: str,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        """Append an activity event to a run outside a dispatch.

        For platform actors that act on a run without running a
        step — the API service's drive recording why it stopped —
        so the event lands in the same trail (and outbox) as engine
        events instead of only in a server log.
        """
        with self._edit(run_id) as run:
            self._event(run, event_type, message, metadata=metadata)

    def _event(
        self,
        run: WorkflowExecution,
        event_type: str,
        message: str,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        event = ActivityEvent(
            id=self._new_id(),
            timestamp=self._now(),
            project_id=run.project_id,
            task_id=run.task_id,
            workflow_id=self._definition.id,
            event_type=event_type,
            message=message,
            metadata={"runId": run.id, "stage": run.state.stage, **(metadata or {})},
        )
        run.observations.append(Observation(id=event.id, event=event))

    def _now(self) -> datetime:
        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Clock must return a timezone-aware datetime")
        return now

    def start(
        self,
        *,
        task_id: str,
        project_id: str,
        inputs: Mapping[str, dict[str, Any]] | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> WorkflowExecution:
        if not task_id.strip() or not project_id.strip():
            raise ValueError("task_id and project_id must be nonblank")
        step_ids = {step.id for step in self._definition.steps}
        if inputs is not None and set(inputs) - step_ids:
            raise ValueError("Inputs contain an unknown workflow step")
        if self._code_loop is not None and inputs is not None:
            steps = code_steps(self._definition)
            ref = inputs.get(steps["implement"].id, {}).get("ref")
            for step in steps.values():
                supplied_ref = inputs.get(step.id, {}).get("ref", ref)
                if supplied_ref != ref:
                    raise ValueError("All code steps must use the same base ref")
        now = self._now()
        run_id = self._new_id()
        if not run_id.strip() or run_id in self._runs:
            raise ValueError("Run ID must be nonblank and unique")
        run = WorkflowExecution(
            id=run_id,
            task_id=task_id,
            project_id=project_id,
            state=apply(self._graph, RunState.initial(), Trigger.START),
            inputs=deepcopy(dict(inputs or {})),
            context=deepcopy(dict(context or {})),
            definition=self._definition.to_contract(),
            settings=self._settings(),
            started_at=now,
            updated_at=now,
        )
        self._event(run, "WORKFLOW_STARTED", "Workflow execution started")
        if self._store:
            with self._store.transaction():
                self._store.create_execution(run)
        self._runs[run_id] = run
        return run.snapshot()

    def get(self, run_id: str, *, copy: bool = True) -> WorkflowExecution:
        """The run, as an independent copy by default.

        ``copy=False`` returns the live stored object for internal
        read-only paths (view building, observation scans): callers
        must not mutate it. Public callers keep the safe default.
        """
        run = self._load(run_id)
        return run.snapshot() if copy else run

    def workflow_run(self, run_id: str) -> dict[str, Any]:
        run = self.get(run_id, copy=False)
        status = run_status(self._graph, run.state.stage)
        if run.retry_at is not None:
            status = "WAITING"
        return run.workflow_run(status, self._definition.id, self._definition.version)

    def task(self, run_id: str) -> dict[str, Any]:
        run = self.get(run_id, copy=False)
        return {
            "id": run.task_id,
            "projectId": run.project_id,
            "workflowId": self._definition.id,
            "title": run.task_id,
            "description": "",
            "priority": "NORMAL",
            "assignedAgent": None,
            "status": "WAITING" if run.retry_at else task_status(self._graph, run.state.stage),
            "stage": run.state.stage,
            "artifacts": [artifact.to_contract() for artifact in run.artifact_history.values()],
            "createdAt": run.started_at.isoformat(),
            "updatedAt": run.updated_at.isoformat(),
            "metadata": {"runId": run.id},
        }

    def _step(self, run: WorkflowExecution) -> WorkflowStepDef:
        if run.state.stage in (FIX_STAGE, ESCALATED_STAGE):
            return WorkflowStepDef(
                id=FIX_STEP,
                name="Fix code",
                type="AGENT",
                stage=FIX_STAGE,
                agent_type="fix",
                requires_approval=False,
                consumes=["SPEC", "PLAN", "TASK", "CODE", "CODE_REVIEW"],
                produces=["CODE"],
                retry_policy=self._code_loop.fix_retry_policy if self._code_loop else None,
            )
        step_id = next(
            stage.step_id for stage in self._graph.stages if stage.name == run.state.stage
        )
        return next(step for step in self._definition.steps if step.id == step_id)

    def _announce_step_start(self, run: WorkflowExecution) -> None:
        step = self._step(run)
        attempt = run.attempts.get(step.id, 0) + 1
        message = f"{step.name} started"
        if step.agent_type == "implement" and run.task_order:
            message += f" · item {run.task_order[run.item_index]}"
        if attempt > 1:
            message += f" (attempt {attempt})"
        self._event(
            run,
            "STEP_STARTED",
            message,
            metadata={
                "stepId": step.id,
                "agentType": step.agent_type,
                "attempt": attempt,
            },
        )

    def _fail(
        self,
        run: WorkflowExecution,
        code: str,
        message: str,
        category: Literal["VALIDATION", "AGENT", "WORKFLOW", "APPROVAL", "INTEGRATION"],
    ) -> None:
        run.errors.append(
            PlatformError(
                code=code,
                message=message,
                category=category,
                retryable=False,
                timestamp=self._now(),
            )
        )
        run.state = apply(self._graph, run.state, Trigger.FAIL)
        self._event(run, "WORKFLOW_FAILED", message)

    def tick(self, run_id: str) -> WorkflowExecution:
        if run_id in self._active:
            raise ValueError("A run cannot be dispatched recursively")
        # Phase 1 — claim, in one short transaction: validate the run,
        # stamp the in_flight token and persist the step-start event.
        # The store's write lock is released when this block exits.
        token: str | None = None
        with self._edit(run_id, lock=True) as run:
            if run.paused:
                return self.get(run_id)
            if run.in_flight is not None:
                raise ValueError("Interrupted dispatch requires explicit recover() before retry")
            kind = kind_of(self._graph, run.state.stage)
            if kind in (StageKind.COMPLETED, StageKind.FAILED, StageKind.CANCELLED):
                raise InvalidTransition(run.state.stage, Trigger.COMPLETE.value)
            if kind == StageKind.REVIEW:
                self._sync_approval(run)
                token = ai_stage(self).claim(run)
            elif kind != StageKind.ESCALATED and (
                run.retry_at is None or self._now() >= run.retry_at
            ):
                run.retry_at = None
                run.in_flight = self._new_id()
                token = run.in_flight
                # Record the step start before dispatching: the
                # claim is saved when the block exits, so the run's
                # log shows what the agent is doing while a long
                # step (e.g. a minutes-long model call) is still in
                # flight, not only after it finishes.
                self._announce_step_start(run)
        if token is None:
            return self.get(run_id)
        # Phase 2 — execute with NO store transaction held. The agent
        # call (a model request; potentially minutes) works on the
        # claimed snapshot while other runs and writers keep using the
        # store. Correctness no longer relies on this process's
        # _active guard: the in_flight token and the row version do.
        claimed = run.snapshot()
        pre_dispatch = claimed.snapshot()
        review_result: AgentResult | None = None
        exceeded = (
            budget_exceeded_message(claimed, self._budget) if self._budget is not None else None
        )
        if exceeded is not None:
            # The budget is checked BEFORE dispatch: an over-budget
            # run fails here and the model is never called again.
            self._fail(claimed, "RUN_BUDGET_EXCEEDED", exceeded, "WORKFLOW")
        else:
            self._active.add(run_id)
            try:
                review_result = dispatch_claimed(self, claimed)
            finally:
                self._active.remove(run_id)
        # Phase 3 — commit, in one short transaction: the claim token
        # must still own the run. If it does not (a recover(), or a
        # version-guarded save elsewhere), this dispatch's outcome is
        # stale: drop it and fail loudly instead of overwriting.
        with self._store.transaction() if self._store else nullcontext():
            stored = self._load(run_id)
            if stored.in_flight != token:
                raise ConcurrentModificationError(
                    f"Run '{run_id}' changed hands while its dispatch"
                    " executed; the dispatch result was discarded",
                )
            apply_review_result(self, claimed, review_result)
            if claimed._pending_approval is not None:
                # The deferred approval request, created here so it
                # commits (or rolls back) together with the checkpoint
                # that references it.
                spec = claimed._pending_approval
                claimed._pending_approval = None
                service, policy = self._approval_dependencies()
                failure: (
                    tuple[
                        str,
                        str,
                        Literal["VALIDATION", "INTEGRATION"],
                    ]
                    | None
                ) = None
                try:
                    approval = service.request(
                        spec, ai_stage(self).policy_for(claimed, spec, policy), self._now()
                    )
                except ApprovalError:
                    failure = (
                        "VALIDATION_FAILED",
                        "Approval request could not be created",
                        "VALIDATION",
                    )
                except Exception:
                    failure = (
                        "INTEGRATION_UNAVAILABLE",
                        "Approval repository could not create the request",
                        "INTEGRATION",
                    )
                if failure is None:
                    claimed.approval_id = approval.id
                else:
                    # The step's application is rejected as a whole,
                    # exactly as when the request was made during the
                    # dispatch: nothing the step produced is published.
                    claimed.artifacts = pre_dispatch.artifacts
                    claimed.artifact_history = pre_dispatch.artifact_history
                    claimed.state = pre_dispatch.state
                    claimed.feedback = pre_dispatch.feedback
                    claimed.retry_attempts = pre_dispatch.retry_attempts
                    self._fail(claimed, *failure)
            if claimed.state.stage != stored.state.stage:
                self._event(
                    claimed,
                    "WORKFLOW_COMPLETED"
                    if claimed.state.stage == "COMPLETED"
                    else "WORKFLOW_STAGE_CHANGED",
                    "Workflow stage changed",
                )
            claimed.in_flight = None
            claimed.touch(self._now())
            if self._store:
                self._store.save_execution(claimed)
            self._runs[run_id] = claimed
        return self.get(run_id)

    def _dispatch(self, run: WorkflowExecution) -> None:
        """Prepare, execute and apply one step.

        Preparation and application mutate only the (claimed) run copy
        they are handed; the execute call between them is the one part
        allowed to take real time, and tick() runs it outside any
        store transaction.
        """
        prepared = self._prepare_dispatch(run)
        if prepared is None:
            return
        step, agent_id, execute, request = prepared
        try:
            result = execute(request)
        except Exception:
            self._fail(
                run,
                "AGENT_EXECUTION_FAILED",
                "Agent raised outside its result contract",
                "AGENT",
            )
            return
        self._apply_result(run, step, agent_id, request, result)

    def _prepare_dispatch(
        self,
        run: WorkflowExecution,
    ) -> (
        tuple[
            WorkflowStepDef,
            str,
            Callable[[AgentRequest], AgentResult],
            AgentRequest,
        ]
        | None
    ):
        """Resolve the step's executor and build its AgentRequest.

        Returns None when preparation itself settles the run (the
        failure has already been recorded on it via _fail).
        """
        step = self._step(run)
        if (
            self._code_loop is not None
            and step.agent_type == "implement"
            and not self._select_item(run, step)
        ):
            return None
        if step.action is not None and step.agent_type is None:
            execute = self._actions.get(step.action)
            if execute is None:
                self._fail(
                    run,
                    "INTEGRATION_UNAVAILABLE",
                    "Workflow action has no handler",
                    "INTEGRATION",
                )
                return None
            agent_id = "action:" + step.action
        else:
            if step.type != "AGENT" or step.agent_type is None or step.action is not None:
                self._fail(
                    run,
                    "INTEGRATION_UNAVAILABLE",
                    "Workflow step type is unsupported",
                    "INTEGRATION",
                )
                return None
            try:
                agent = self._registry.for_type(step.agent_type)
            except KeyError:
                self._fail(run, "AGENT_NOT_REGISTERED", "No agent registered for step", "AGENT")
                return None
            metadata = agent.get_metadata()
            if metadata.status != "IDLE":
                self._fail(run, "AGENT_EXECUTION_FAILED", "Agent is not available", "AGENT")
                return None
            agent_id = metadata.id
            execute = agent.execute
        if any(kind not in run.artifacts for kind in step.consumes):
            self._fail(
                run,
                "VALIDATION_FAILED",
                "Required upstream artifact is missing",
                "VALIDATION",
            )
            return None
        types = list(step.consumes)
        if step.id == FIX_STEP and "TEST_REPORT" in run.artifacts:
            types.append("TEST_REPORT")
        if step.agent_type == "review" and "TEST_REPORT" in run.artifacts:
            # A re-review after a fix can see the latest test report:
            # the review prompt tails it, and the configured
            # skip-when-tests-pass fast path keys off it. The first
            # review (no report exists yet) is unaffected.
            types.append("TEST_REPORT")
        if run.feedback:
            types.extend(kind for kind in step.produces if kind not in types)
        artifacts = [run.artifacts[kind] for kind in types if kind in run.artifacts]
        attempt = run.attempts.get(step.id, 0) + 1
        inputs = deepcopy(run.inputs.get(step.id, {}))
        if self._code_loop is not None and step.agent_type in (
            "implement",
            "review",
            "test",
            "fix",
        ):
            base_inputs = run.inputs.get(code_steps(self._definition)["implement"].id, {})
            inputs["ref"] = base_inputs.get("ref")
            inputs["taskItemId"] = run.task_order[run.item_index]
            if "language" in base_inputs:
                inputs.setdefault("language", base_inputs["language"])
        if step.id == FIX_STEP:
            # A re-dispatched fix (a step retry, or a run resumed after
            # its fix attempt failed) must know WHY the last attempt was
            # rejected. The failure travels in the run's results — which
            # a resume fork carries over — and without it the model is
            # re-prompted with identical context and repeats the
            # identical invalid reply, so Resume could never succeed.
            latest_fix = next(
                (r for r in reversed(run.results) if r.agent_id == agent_id),
                None,
            )
            if latest_fix is not None and latest_fix.status != "SUCCESS" and latest_fix.errors:
                error = latest_fix.errors[0]
                summary = f"{error.code}: {error.message}"
                if error.details:
                    summary += (
                        " — "
                        + json.dumps(
                            error.details,
                            default=str,
                        )[:500]
                    )
                inputs["previousFixError"] = summary
        request_metadata: dict[str, Any] = {
            "attempt": attempt,
            "runId": run.id,
            "stepId": step.id,
        }
        if step.timeout is not None:
            # The step's configured timeout becomes a live deadline:
            # BaseAgent turns it into per-call remaining time for the
            # gateway instead of the timeout only being checked after
            # the agent returns.
            request_metadata["stepTimeoutSeconds"] = step.timeout
        request = AgentRequest(
            request_id=run.in_flight or self._new_id(),
            task_id=run.task_id,
            project_id=run.project_id,
            workflow_id=self._definition.id,
            agent_id=agent_id,
            input=inputs,
            context=deepcopy(run.context),
            artifacts=deepcopy(artifacts),
            feedback=deepcopy(run.feedback),
            metadata=request_metadata,
        )
        run.attempts[step.id] = attempt
        return step, agent_id, execute, request

    def _apply_result(
        self,
        run: WorkflowExecution,
        step: WorkflowStepDef,
        agent_id: str,
        request: AgentRequest,
        result: AgentResult,
    ) -> None:
        """Validate one execution result and apply it to the run."""
        if (
            not isinstance(result, AgentResult)
            or result.request_id != request.request_id
            or result.agent_id != agent_id
        ):
            self._fail(run, "VALIDATION_FAILED", "Agent result identity is invalid", "VALIDATION")
            return
        run.results.append(result.model_copy(deep=True))
        for event in result.events:
            run.observations.append(Observation(id=event.id, event=event.model_copy(deep=True)))
        run.observations.append(
            Observation(
                id=result.request_id + ":metrics",
                result=result.model_copy(deep=True),
            )
        )
        if result.status == "CANCELLED":
            run.state = apply(self._graph, run.state, Trigger.CANCEL)
            return
        if result.status != "SUCCESS" or result.errors:
            if self._retry(run, step, result):
                return
            if result.errors:
                run.errors.extend(error.model_copy(deep=True) for error in result.errors)
                run.state = apply(self._graph, run.state, Trigger.FAIL)
            else:
                self._fail(run, "AGENT_EXECUTION_FAILED", "Agent did not succeed", "AGENT")
            return
        if step.timeout is not None and result.metrics.duration_seconds > step.timeout:
            self._fail(run, "WORKFLOW_STEP_TIMEOUT", "Step exceeded configured timeout", "WORKFLOW")
            return
        if (
            sorted(artifact.type for artifact in result.artifacts) != sorted(step.produces)
            or any(artifact.created_by != agent_id for artifact in result.artifacts)
            or len({artifact.id for artifact in result.artifacts}) != len(result.artifacts)
            or any(artifact.id in run.artifact_history for artifact in result.artifacts)
        ):
            self._fail(run, "VALIDATION_FAILED", "Agent output artifacts are invalid", "VALIDATION")
            return
        verdict = result.output.get("verdict") if isinstance(result.output, dict) else None
        expected_verdict = {"review": "APPROVE", "test": "PASS"}.get(step.agent_type or "")
        if self._code_loop is not None and step.agent_type in ("review", "test"):
            allowed = (
                ("APPROVE", "CHANGES_REQUESTED")
                if step.agent_type == "review"
                else ("PASS", "FAIL")
            )
            if verdict not in allowed:
                self._fail(run, "VALIDATION_FAILED", "Invalid quality verdict", "VALIDATION")
                return
            if not self._linked_output(run, step, result):
                return
            self._publish_artifacts(run, result)
            run.retry_attempts = 0
            if verdict != expected_verdict:
                self._request_fix(run)
            elif step.agent_type == "test" and self._next_item(run):
                return
            else:
                run.state = apply(self._graph, run.state, Trigger.COMPLETE)
            return
        if (verdict is not None and verdict not in ("PASS", "APPROVE")) or (
            expected_verdict is not None and verdict != expected_verdict
        ):
            self._fail(
                run,
                "VALIDATION_FAILED",
                "Quality verdict is not passing; automatic Fix routing is not implemented",
                "VALIDATION",
            )
            return
        # Per-task approval skips (context key skipApprovals, chosen
        # when the task was created): a skipped gate is not requested
        # at all and the run advances straight through it below.
        skipped = step.requires_approval and ai_stage(self).gate_skipped(run, step)
        if step.requires_approval and not skipped:
            # Defer the actual request to tick's commit phase: this
            # phase runs without a store transaction, so creating the
            # approval here would orphan a PENDING request whenever
            # the commit then failed. The commit creates it inside
            # its own transaction, atomically with the checkpoint.
            run._pending_approval = ApprovalSpec(
                task_id=run.task_id,
                project_id=run.project_id,
                workflow_id=self._definition.id,
                artifact_id=result.artifacts[0].id,
                type=step.produces[0],
                requested_by="orchestrator",
                metadata={"runId": run.id, "stepId": step.id},
            )
        if self._code_loop is not None and step.agent_type in ("implement", "fix"):
            if not self._linked_output(run, step, result):
                return
            run.artifacts.pop("CODE_REVIEW", None)
            run.artifacts.pop("TEST_REPORT", None)
        self._publish_artifacts(run, result)
        run.feedback = []
        run.retry_attempts = 0
        run.state = apply(self._graph, run.state, Trigger.COMPLETE)
        if skipped:
            # Advance through the gate exactly as an approval would
            # (REVIEW -> APPROVED -> next step), leaving an audit
            # event instead of an approval record.
            run.state = apply(self._graph, run.state, Trigger.APPROVED)
            run.state = apply(self._graph, run.state, Trigger.ADVANCE)
            self._event(
                run,
                "APPROVAL_SKIPPED",
                f"{step.name} approval skipped (task setting)",
                metadata={"stepId": step.id},
            )
        self._event(run, "WORKFLOW_ADVANCED", "Workflow step completed")

    def _publish_artifacts(self, run: WorkflowExecution, result: AgentResult) -> None:
        for artifact in result.artifacts:
            run.artifacts[artifact.type] = artifact.model_copy(deep=True)
            run.artifact_history[artifact.id] = artifact.model_copy(deep=True)

    def _select_item(self, run: WorkflowExecution, step: WorkflowStepDef) -> bool:
        if run.task_order:
            return True
        try:
            ordered = ordered_task_ids(run.artifacts["TASK"])
            if self._code_loop is not None and not self._code_loop.all_task_items:
                chosen = run.inputs.get(step.id, {}).get("taskItemId")
                if chosen not in ordered:
                    raise ValueError("Selected task item is unknown")
                ordered = [chosen]
            ref = run.inputs.get(step.id, {}).get("ref")
            if not isinstance(ref, str) or not ref.strip():
                raise ValueError("A base ref is required for code execution")
        except (KeyError, ValueError, TypeError):
            self._fail(
                run,
                "VALIDATION_FAILED",
                "Invalid TASK dependency graph or code base ref",
                "VALIDATION",
            )
            return False
        run.task_order = ordered
        return True

    def _linked_output(
        self,
        run: WorkflowExecution,
        step: WorkflowStepDef,
        result: AgentResult,
    ) -> bool:
        artifact = result.artifacts[0]
        item_id = run.task_order[run.item_index]
        base_inputs = run.inputs.get(code_steps(self._definition)["implement"].id, {})
        expected = {"taskItemId": item_id, "baseRef": base_inputs.get("ref")}
        for kind in ("SPEC", "PLAN", "TASK"):
            upstream = run.artifacts.get(kind)
            if upstream is not None:
                expected[kind.lower() + "ArtifactId"] = upstream.id
                expected[kind.lower() + "Version"] = upstream.version
        code = run.artifacts.get("CODE")
        if step.agent_type in ("review", "test") and code is not None:
            expected.update(codeArtifactId=code.id, codeVersion=code.version)
            wrapper = "review" if step.agent_type == "review" else "report"
            payload = artifact.content.get(wrapper) if isinstance(artifact.content, dict) else None
            output = result.output if isinstance(result.output, dict) else {}
            if not isinstance(payload, dict) or payload.get("verdict") != output.get("verdict"):
                self._fail(run, "VALIDATION_FAILED", "Inconsistent quality artifact", "VALIDATION")
                return False
        if any(artifact.metadata.get(key) != value for key, value in expected.items()):
            self._fail(run, "VALIDATION_FAILED", "Stale code-chain artifact links", "VALIDATION")
            return False
        if (
            step.agent_type == "fix"
            and code is not None
            and (
                not code.version.isdecimal()
                or artifact.version != str(int(code.version) + 1)
                or artifact.metadata.get("revisionOf") != code.id
            )
        ):
            self._fail(
                run,
                "VALIDATION_FAILED",
                "Invalid replacement CODE revision",
                "VALIDATION",
            )
            return False
        return True

    def _request_fix(self, run: WorkflowExecution) -> None:
        run.state = apply(self._graph, run.state, Trigger.REQUEST_CHANGES)
        run.state = apply(self._graph, run.state, Trigger.REVISE)
        used = run.state.revisions.get(FIX_STEP, 0)
        budget = self._graph.max_revisions.get(FIX_STEP, used)
        if run.state.stage == ESCALATED_STAGE:
            self._event(
                run,
                "WORKFLOW_ESCALATED",
                f"Fix budget exhausted ({used}/{budget}) — waiting for operator",
            )
        else:
            self._event(
                run,
                "CODE_FIX_REQUESTED",
                f"Review/Test requested changes — fix {used}/{budget}",
            )

    def _next_item(self, run: WorkflowExecution) -> bool:
        item_id = run.task_order[run.item_index]
        run.item_results[item_id] = {
            kind: run.artifacts[kind].model_copy(deep=True)
            for kind in ("CODE", "CODE_REVIEW", "TEST_REPORT")
        }
        if run.item_index + 1 == len(run.task_order):
            return False
        run.item_index += 1
        for kind in ("CODE", "CODE_REVIEW", "TEST_REPORT"):
            run.artifacts.pop(kind, None)
        revisions = dict(run.state.revisions)
        revisions.pop(FIX_STEP, None)
        run.state = RunState(stage=run.state.stage, revisions=revisions)
        run.state = apply(self._graph, run.state, Trigger.ADVANCE)
        self._event(
            run,
            "TASK_ITEM_ADVANCED",
            "Task item verified; next dependency-ready item selected",
        )
        return True

    def _retry(
        self,
        run: WorkflowExecution,
        step: WorkflowStepDef,
        result: AgentResult,
    ) -> bool:
        policy = step.retry_policy
        run.retry_attempts += 1
        if (
            policy is None
            or result.status != "FAILED"
            or not result.errors
            or run.retry_attempts >= policy.max_attempts
            or any(not error.retryable for error in result.errors)
            or (
                policy.retry_on is not None
                and any(error.code not in policy.retry_on for error in result.errors)
            )
        ):
            return False
        # Clock-driven scheduling: tick never sleeps or calls the provider before due time.
        delay = min((policy.backoff_seconds or 0) * (2 ** min(run.retry_attempts - 1, 16)), 3600)
        run.retry_at = self._now() + timedelta(seconds=delay)
        self._event(run, "WORKFLOW_RETRY_SCHEDULED", "Retryable step failure scheduled")
        return True

    def _approval_dependencies(self) -> tuple[ApprovalService, ApprovalPolicy]:
        if self._approvals is None or self._approval_policy is None:
            raise ValueError("Approval dependencies are not configured")
        return self._approvals, self._approval_policy

    def _sync_approval(self, run: WorkflowExecution) -> None:
        service, _ = self._approval_dependencies()
        if run.approval_id is None:
            raise ValueError("Review stage is missing its approval request")
        request = service.get(run.approval_id)
        now = self._now()
        if (
            request.status == "PENDING"
            and request.expires_at is not None
            and request.expires_at <= now
        ):
            service.expire_due(now)
            request = service.get(run.approval_id)
        if request.status == "PENDING":
            return
        if request.status == "APPROVED":
            run.state = apply(self._graph, run.state, Trigger.APPROVED)
            run.state = apply(self._graph, run.state, Trigger.ADVANCE)
            run.approval_id = None
        elif request.status in ("REJECTED", "CHANGES_REQUESTED"):
            run.feedback = service.feedback_for(request.id)
            run.state = apply(self._graph, run.state, Trigger.REJECTED)
            run.state = apply(self._graph, run.state, Trigger.REVISE)
            run.approval_id = None
        elif request.status == "CANCELLED":
            run.state = apply(self._graph, run.state, Trigger.CANCEL)
        else:
            self._fail(run, "APPROVAL_EXPIRED", "Approval request expired", "APPROVAL")

    def pending_approval(self, run_id: str) -> ApprovalRequest:
        """Return the current pending approval without exposing repository internals."""
        run = self.get(run_id)
        if run.approval_id is None:
            raise ApprovalError("NOT_FOUND", "Workflow has no pending approval")
        service, _ = self._approval_dependencies()
        request = service.get(run.approval_id)
        if request.status != "PENDING":
            raise ApprovalError("APPROVAL_ALREADY_DECIDED", "Approval is no longer pending")
        if request.expires_at is not None and request.expires_at <= self._now():
            raise ApprovalError("APPROVAL_EXPIRED", "Approval request has expired")
        return request

    def decide(
        self,
        run_id: str,
        *,
        reviewer: str,
        decision: Literal["APPROVED", "REJECTED", "REQUEST_CHANGES"],
        comment: str = "",
        expected_approval_id: str | None = None,
    ) -> WorkflowExecution:
        if run_id in self._active:
            raise ValueError("A running dispatch cannot be changed recursively")
        expired: ApprovalError | None = None
        with self._edit(run_id) as run:
            if expected_approval_id is not None and run.approval_id != expected_approval_id:
                raise ApprovalError(
                    "APPROVAL_ALREADY_DECIDED",
                    "Card does not refer to the current approval",
                )
            if run.in_flight is not None:
                raise ValueError("Interrupted dispatch requires recovery")
            try:
                self._decide(run, reviewer=reviewer, decision=decision, comment=comment)
            except ApprovalError as error:
                if error.code != "APPROVAL_EXPIRED":
                    raise
                self._sync_approval(run)
                expired = error
        if expired is not None:
            raise expired
        return self.get(run_id)

    def _decide(
        self,
        run: WorkflowExecution,
        *,
        reviewer: str,
        decision: Literal["APPROVED", "REJECTED", "REQUEST_CHANGES"],
        comment: str,
    ) -> None:
        if kind_of(self._graph, run.state.stage) != StageKind.REVIEW or run.approval_id is None:
            raise InvalidTransition(run.state.stage, decision)
        service, _ = self._approval_dependencies()
        service.decide(
            ApprovalDecision(
                approval_id=run.approval_id,
                reviewer=reviewer,
                decision=decision,
                comment=comment,
                created_at=self._now(),
            )
        )
        self._sync_approval(run)
        self._event(run, "APPROVAL_DECIDED", "Approval decision processed")

    def cancel(self, run_id: str) -> WorkflowExecution:
        if run_id in self._active:
            raise ValueError("A running dispatch cannot be changed recursively")
        with self._edit(run_id) as run:
            if run.in_flight is not None:
                raise ValueError("Interrupted dispatch requires recovery")
            self._cancel(run)
        return self.get(run_id)

    def _cancel(self, run: WorkflowExecution) -> None:
        if Trigger.CANCEL.value not in allowed_triggers(self._graph, run.state.stage):
            raise InvalidTransition(run.state.stage, Trigger.CANCEL.value)
        if run.approval_id is not None:
            service, _ = self._approval_dependencies()
            if service.get(run.approval_id).status == "PENDING":
                service.cancel(run.approval_id, self._now())
        run.state = apply(self._graph, run.state, Trigger.CANCEL)
        run.retry_at = None
        self._event(run, "WORKFLOW_CANCELLED", "Workflow execution cancelled")

    def resume(self, run_id: str, *, reason: str, operator: str = "operator") -> WorkflowExecution:
        if not reason.strip():
            raise ValueError("An explicit operator reason is required")
        if run_id in self._active:
            raise ValueError("A running dispatch cannot be resumed")
        with self._edit(run_id) as run:
            if kind_of(self._graph, run.state.stage) != StageKind.ESCALATED:
                raise InvalidTransition(run.state.stage, Trigger.RESUME.value)
            run.state = apply(self._graph, run.state, Trigger.RESUME)
            # RESUME resets the state-machine budget; the next Fix uses its first slot.
            if run.state.stage == FIX_STAGE:
                if self._code_loop is None or self._code_loop.max_fixes == 0:
                    raise ValueError("A zero Fix budget cannot be resumed")
                run.state = RunState(
                    stage=run.state.stage,
                    revisions={**run.state.revisions, FIX_STEP: 1},
                )
            run.retry_attempts = 0
            run.recovery_notes.append(reason)
            self._event(
                run,
                "WORKFLOW_RESUMED",
                "Operator resumed an escalated execution",
                metadata={"reason": reason, "operator": operator},
            )
        return self.get(run_id)

    def resume_failed(self, run_id: str) -> WorkflowExecution:
        """Fork a FAILED run into a new execution that re-runs the failed step.

        The source run stays untouched as the immutable record of the
        failure. The new run carries over the source's inputs, context,
        artifacts (latest and history), results, task-item progress and
        revision counters, rewound to the stage the source was in when it
        failed — approved SPEC/PLAN/TASK artifacts are reused and only
        the failed step (and what follows it) executes again.
        """
        if run_id in self._active:
            raise ValueError("A running dispatch cannot be resumed")
        source = self._load(run_id)
        if kind_of(self._graph, source.state.stage) != StageKind.FAILED:
            raise ValueError(
                f"Run '{run_id}' has not failed (stage {source.state.stage}); "
                "only a failed run can be resumed",
            )
        if source.in_flight is not None:
            raise ValueError(
                "Interrupted dispatch requires explicit recover() before resume",
            )
        stage = self._failed_stage(source)
        # An operator resuming a run that died in the code loop is
        # explicitly granting it another round: the fix budget
        # starts over (the spent FIX_STEP counter is dropped, like
        # _next_item does between items) while the spec/plan/task
        # revision counters are kept — those approvals are reused,
        # not re-earned. retry_attempts is not carried over either
        # (the fork constructor leaves it at 0).
        revisions = dict(source.state.revisions)
        fix_budget_reset = revisions.pop(FIX_STEP, None) is not None
        # The failed step's dispatch-attempt counter also starts
        # over, so its next STEP_STARTED reads "attempt 1", not a
        # number accumulated across every fork of this run.
        attempts = dict(source.attempts)
        failed_step_id = FIX_STEP if stage in _LOOP_STAGES else None
        if failed_step_id is None:
            for step in self._definition.steps:
                if stage in step.generated_stages():
                    failed_step_id = step.id
                    break
        if failed_step_id is not None:
            attempts.pop(failed_step_id, None)
        now = self._now()
        new_run_id = self._new_id()
        if not new_run_id.strip() or new_run_id in self._runs:
            raise ValueError("Run ID must be nonblank and unique")
        run = WorkflowExecution(
            id=new_run_id,
            task_id=source.task_id,
            project_id=source.project_id,
            state=RunState(stage=stage, revisions=revisions),
            inputs=deepcopy(source.inputs),
            context=deepcopy(source.context),
            artifacts=deepcopy(source.artifacts),
            results=deepcopy(source.results),
            errors=deepcopy(source.errors),
            feedback=deepcopy(source.feedback),
            attempts=attempts,
            approval_id=(
                source.approval_id if kind_of(self._graph, stage) == StageKind.REVIEW else None
            ),
            definition=self._definition.to_contract(),
            settings=self._settings(),
            started_at=now,
            updated_at=now,
            task_order=list(source.task_order),
            item_index=source.item_index,
            item_results=deepcopy(source.item_results),
            artifact_history=deepcopy(source.artifact_history),
            observations=deepcopy(source.observations),
            recovery_notes=[
                *source.recovery_notes,
                f"Resumed from failed run {source.id}: "
                f"re-running the step that failed at stage {stage}",
                *(
                    ["Fix budget reset by operator resume: FIX_STEP counter back to 0"]
                    if fix_budget_reset
                    else []
                ),
            ],
        )
        self._event(run, "WORKFLOW_RESUMED", f"Resumed from failed run {source.id}")
        if self._store:
            with self._store.transaction():
                self._store.create_execution(run)
        self._runs[new_run_id] = run
        return run.snapshot()

    def _failed_stage(self, run: WorkflowExecution) -> str:
        """The stage a FAILED run was in when it failed.

        Read back from the run's own stage-change trail; the fallback is
        the first step whose outputs were never published (the same rule
        the dashboard uses to mark the failed step).
        """
        terminal = (
            StageKind.FAILED,
            StageKind.COMPLETED,
            StageKind.CANCELLED,
            StageKind.ESCALATED,
        )
        for observation in reversed(run.observations):
            event = observation.event
            if event is None or event.event_type not in (
                "WORKFLOW_STARTED",
                "WORKFLOW_STAGE_CHANGED",
            ):
                continue
            stage = event.metadata.get("stage")
            if (
                isinstance(stage, str)
                and stage != run.state.stage
                and kind_of(self._graph, stage) not in terminal
            ):
                return stage
        produced = {artifact.type for artifact in run.artifact_history.values()}
        for step in self._definition.steps:
            if step.produces and not set(step.produces) <= produced:
                return step.generated_stages()[0]
        return self._definition.steps[-1].generated_stages()[0]

    def recover(
        self,
        run_id: str,
        *,
        reason: str,
        retry_interrupted: bool = False,
        operator: str = "operator",
    ) -> WorkflowExecution:
        if run_id in self._active or not reason.strip():
            raise ValueError("Recovery requires an inactive run and an operator reason")
        with self._edit(run_id) as run:
            if run.in_flight is None:
                raise ValueError("No interrupted dispatch to recover")
            run.in_flight = None
            run.recovery_notes.append(reason)
            if retry_interrupted:
                self._event(
                    run,
                    "WORKFLOW_RECOVERED",
                    "Operator accepted possible duplicate external execution",
                    metadata={"reason": reason, "operator": operator},
                )
            else:
                self._fail(
                    run,
                    "AGENT_EXECUTION_FAILED",
                    "Interrupted dispatch not replayed",
                    "AGENT",
                )
        return self.get(run_id)

    def fail_run(
        self, run_id: str, *, reason: str, operator: str = "operator"
    ) -> WorkflowExecution:
        """Fail a live run under operator control.

        For runs that will never move again on their own — an
        escalation the operator gives up on, a stalled run whose
        step is lost — so the failure is recorded (and resumable
        via resume_failed) instead of the run lingering forever.
        Terminal runs refuse. An interrupted dispatch marker is
        cleared first: the operator's decision supersedes it.
        """
        if not reason.strip():
            raise ValueError("An explicit operator reason is required")
        if run_id in self._active:
            raise ValueError("A running dispatch cannot be failed by an operator")
        with self._edit(run_id) as run:
            kind = kind_of(self._graph, run.state.stage)
            if kind in (StageKind.COMPLETED, StageKind.FAILED, StageKind.CANCELLED):
                raise InvalidTransition(run.state.stage, Trigger.FAIL.value)
            run.in_flight = None
            run.recovery_notes.append(reason)
            self._event(
                run,
                "RUN_FAILED_BY_OPERATOR",
                f"Operator failed the run: {reason}",
                metadata={"reason": reason, "operator": operator},
            )
            self._fail(run, "OPERATOR_FAILED", f"Failed by operator: {reason}", "WORKFLOW")
        return self.get(run_id)

    def set_paused(
        self, run_id: str, paused: bool, *, reason: str = "", operator: str = "operator"
    ) -> WorkflowExecution:
        """Set or clear the operator pause flag, with an audit event.

        Pausing never interrupts a step mid-flight: tick() stops
        claiming new steps, so the run parks at the next step
        boundary. Terminal runs refuse a pause (nothing to pause);
        clearing a pause is always allowed on a live run.
        """
        if run_id in self._active:
            raise ValueError("A running dispatch cannot be (un)paused")
        with self._edit(run_id) as run:
            kind = kind_of(self._graph, run.state.stage)
            if kind in (StageKind.COMPLETED, StageKind.FAILED, StageKind.CANCELLED):
                raise InvalidTransition(run.state.stage, "PAUSE")
            if run.paused == paused:
                return self.get(run_id)
            run.paused = paused
            self._event(
                run,
                "RUN_PAUSED" if paused else "RUN_CONTINUED",
                "Operator paused the run" if paused else "Operator continued the run",
                metadata={"reason": reason, "operator": operator},
            )
        return self.get(run_id)

    def flush_observations(self, run_id: str) -> WorkflowExecution:
        if run_id in self._active:
            raise ValueError("Cannot deliver observations during dispatch")
        self._active.add(run_id)
        try:
            return self._deliver_observations(run_id)
        finally:
            self._active.remove(run_id)

    def _deliver_observations(self, run_id: str) -> WorkflowExecution:
        # Delivery is at-least-once. Consumers deduplicate by
        # event.id/request_id. All pending observations are published
        # first, then the delivered marks are persisted in ONE edit —
        # the old shape re-saved the entire execution once per
        # observation, which made a run with N observations cost N
        # full serializations. On a publish failure, exactly the
        # observations delivered so far are marked before raising, so
        # the failed one (and everything after it) stays pending.
        pending = [
            observation
            for observation in self.get(run_id, copy=False).observations
            if not observation.delivered
            and not (observation.event is not None and self._events is None)
            and not (observation.result is not None and self._metrics is None)
        ]
        delivered: list[str] = []
        failed = False
        for observation in pending:
            try:
                if observation.event is not None and self._events is not None:
                    self._events.publish(observation.event)
                if observation.result is not None and self._metrics is not None:
                    self._metrics.record(
                        observation.result.agent_id,
                        observation.result,
                        run_id=run_id,
                    )
            except Exception:
                failed = True
                break
            delivered.append(observation.id)
        if delivered:
            with self._edit(run_id) as run:
                by_id = {item.id: item for item in run.observations}
                for observation_id in delivered:
                    stored = by_id.get(observation_id)
                    if stored is not None:
                        stored.delivered = True
        if failed:
            raise RuntimeError(
                "Observation delivery failed; record remains pending",
            )
        return self.get(run_id)
