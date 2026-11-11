"""Phase 12 Stage C: the AI review loop inside the orchestrator.

Engines are assembled with scripted producers (DummyAgent) and the
real artifact-review agent over a ScriptedModelGateway, so every
scenario is deterministic and offline: happy path, revise loop,
exhaustion, stagnation, reviewer failure, budget, override, crash
safety and the human/none modes.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from itertools import count
from typing import Any

import pytest

from asf.agents.artifact_review import ArtifactReviewAgent, ArtifactReviewSettings
from asf.agents.base import AgentRuntime
from asf.agents.loading import load_artifact_review_prompts
from asf.approval.models import ApprovalDecision, ApprovalPolicy
from asf.approval.service import ApprovalService
from asf.contracts.models import AgentMetadata, Artifact, PlatformError
from asf.models.errors import ModelGatewayError
from asf.models.fake import ScriptedModelGateway
from asf.orchestrator import AgentRegistry, Orchestrator
from asf.orchestrator.ai_review_apply import _short_error_message
from asf.orchestrator.execution import WorkflowExecution
from asf.orchestrator.gate_ops import approve_anyway, deliver_guidance
from asf.state_machine.machine import InvalidTransition
from asf.storage.memory import InMemoryApprovalRepository, InMemoryStore
from asf.workflow.definition import WorkflowDefinition, WorkflowStepDef
from tests.unit.test_agent_base import DummyAgent
from tests.unit.test_artifact_review_checks import GOOD_PLAN, GOOD_SPEC

START = datetime(2026, 1, 1, tzinfo=UTC)
APPROVE_REPLY = '{"findings": [], "summary": "Complete and consistent."}'
TASK_CONTENT = {
    "format": "json",
    "tasks": [
        {
            "id": "T1",
            "title": "Build the calculator",
            "description": "Implements REQ-1 and REQ-2; run the tests",
            "acceptanceCriteria": ["REQ-1 works", "REQ-2 works"],
            "dependsOn": [],
            "expectedFiles": ["calculator.py"],
            "verificationHint": "Run the tests",
        }
    ],
}


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def rc_reply(status: str = "NEW") -> str:
    return json.dumps(
        {
            "findings": [
                {
                    "id": "F-001",
                    "severity": "BLOCKER",
                    "category": "TRACEABILITY",
                    "location": "REQ-2",
                    "problem": "REQ-2 has no acceptance criterion.",
                    "required_change": "Add an acceptance criterion for REQ-2.",
                    "status": status,
                }
            ],
            "summary": "One blocking problem.",
        }
    )


RESOLVED_REPLY = rc_reply("RESOLVED")


def md(text: str) -> dict[str, Any]:
    return {"format": "markdown", "text": text}


def gated(
    step_id: str,
    agent_type: str,
    produces: str,
    consumes: list[str],
    *,
    mode: str = "ai",
    max_revisions: int = 3,
) -> WorkflowStepDef:
    return WorkflowStepDef(
        id=step_id,
        name=step_id.title(),
        type="AGENT",
        stage=step_id.upper(),
        agent_type=agent_type,
        requires_approval=True,
        approval_mode=mode,  # type: ignore[arg-type]
        max_revisions=max_revisions,
        max_revisions_explicit=True,
        consumes=consumes,
        produces=[produces],
    )


def plain(step_id: str, agent_type: str, produces: str, consumes: list[str]) -> WorkflowStepDef:
    return WorkflowStepDef(
        id=step_id,
        name=step_id.title(),
        type="AGENT",
        stage=step_id.upper(),
        agent_type=agent_type,
        requires_approval=False,
        consumes=consumes,
        produces=[produces],
    )


class Harness:
    """One engine plus the logs and repositories its tests assert on."""

    def __init__(
        self,
        steps: list[WorkflowStepDef],
        *,
        replies: list[str],
        contents: dict[str, list[dict[str, Any]]],
        store: InMemoryStore | None = None,
        gateway_wrapper: Callable[[ScriptedModelGateway], Any] | None = None,
        definition: WorkflowDefinition | None = None,
    ) -> None:
        self.clock = Clock()
        self.ids = count(1)
        self.gateway = ScriptedModelGateway(replies)
        models: Any = self.gateway
        if gateway_wrapper is not None:
            models = gateway_wrapper(self.gateway)
        runtime = AgentRuntime(
            models=models,
            clock=self.clock,
            new_id=lambda: f"id-{next(self.ids)}",
        )
        registry = AgentRegistry()
        self.requests: dict[str, list[Any]] = {}
        for step in steps:
            if step.agent_type == "artifact-review":
                continue
            self._register_producer(registry, runtime, step, contents)
        reviewer = ArtifactReviewAgent(
            runtime, ArtifactReviewSettings(prompts=load_artifact_review_prompts())
        )
        registry.register(reviewer)
        self.repo = InMemoryApprovalRepository()
        workflow = definition or WorkflowDefinition(
            id="development", name="Development", version="1", steps=steps
        )
        kwargs: dict[str, Any] = {}
        if store is not None:
            kwargs["store"] = store
            self.repo = store.approvals
        else:
            kwargs["approvals"] = ApprovalService(self.repo, id_factory=runtime.new_id)
        self.engine = Orchestrator(
            workflow,
            registry,
            clock=self.clock,
            new_id=runtime.new_id,
            approval_policy=ApprovalPolicy(reviewers=["dashboard"]),
            **kwargs,
        )

    def _register_producer(
        self,
        registry: AgentRegistry,
        runtime: AgentRuntime,
        step: WorkflowStepDef,
        contents: dict[str, list[dict[str, Any]]],
    ) -> None:
        agent_type = step.agent_type or step.id
        log: list[Any] = []
        self.requests[agent_type] = log
        versions = contents.get(agent_type, [{}])

        def behave(request: Any) -> tuple[dict[str, Any], list[Artifact]]:
            log.append(request)
            index = min(len(log) - 1, len(versions) - 1)
            artifact = Artifact(
                id=f"art-{next(self.ids)}",
                type=step.produces[0],
                name=step.produces[0],
                version=str(index + 1),
                content=versions[index],
                created_by=f"agent-{agent_type}",
                created_at=START,
            )
            return {"summary": "done"}, [artifact]

        registry.register(
            DummyAgent(
                runtime,
                metadata=AgentMetadata(
                    id=f"agent-{agent_type}",
                    name=agent_type,
                    type=agent_type,
                    version="1",
                    status="IDLE",
                ),
                run_behavior=behave,
            )
        )

    def start(self, context: dict[str, Any] | None = None) -> WorkflowExecution:
        return self.engine.start(
            task_id="task-1",
            project_id="project-1",
            inputs={"spec": {"requirement": "Build a calculator"}},
            context=context if context is not None else {"project": {"name": "example"}},
        )

    def drive(self, run_id: str, limit: int = 40) -> WorkflowExecution:
        for _ in range(limit):
            run = self.engine.get(run_id)
            stage = run.state.stage
            if stage in ("COMPLETED", "FAILED", "CANCELLED") or stage.endswith("_ESCALATED"):
                break
            before = (stage, len(run.results))
            self.engine.tick(run_id)
            after = self.engine.get(run_id)
            if (after.state.stage, len(after.results)) == before and after.retry_at is None:
                break
        return self.engine.get(run_id)

    def decisions(self) -> list[ApprovalDecision]:
        found: list[ApprovalDecision] = []
        for request in self.repo.list_by_task("task-1"):
            found.extend(self.repo.list_decisions(request.id))
        return found

    def approval_requests(self) -> list[Any]:
        return self.repo.list_by_task("task-1")

    def events(self, run_id: str, event_type: str) -> list[Any]:
        return [
            obs.event
            for obs in self.engine.get(run_id).observations
            if obs.event is not None and obs.event.event_type == event_type
        ]


def full_steps() -> list[WorkflowStepDef]:
    return [
        gated("spec", "spec", "SPEC", []),
        gated("plan", "plan", "PLAN", ["SPEC"]),
        gated("task", "task", "TASK", ["SPEC", "PLAN"]),
        plain("implement", "implement", "CODE", ["TASK"]),
    ]


def full_contents() -> dict[str, list[dict[str, Any]]]:
    return {
        "spec": [md(GOOD_SPEC)],
        "plan": [md(GOOD_PLAN)],
        "task": [TASK_CONTENT],
        "implement": [{"text": "code"}],
    }


def test_happy_path_all_gates_ai_approved_without_human_actions() -> None:
    harness = Harness(full_steps(), replies=[APPROVE_REPLY] * 3, contents=full_contents())
    run = harness.start()
    run = harness.drive(run.id)
    assert run.state.stage == "COMPLETED"
    assert len(harness.gateway.requests) == 3
    requests = harness.approval_requests()
    assert len(requests) == 3
    assert all(request.reviewers == ["ai-reviewer", "dashboard"] for request in requests)
    assert all(request.min_approvals == 1 for request in requests)
    assert all(request.status == "APPROVED" for request in requests)
    decisions = harness.decisions()
    assert len(decisions) == 3
    assert all(d.reviewer == "ai-reviewer" and d.reviewer_kind == "AI" for d in decisions)
    reviews = [a for a in run.artifact_history.values() if a.type == "ARTIFACT_REVIEW"]
    assert len(reviews) == 3
    assert {event.metadata["stage"] for event in harness.events(run.id, "AI_REVIEW_COMPLETED")} == {
        "spec",
        "plan",
        "task",
    }


def test_revise_loop_feedback_reaches_producer_and_revisions_count() -> None:
    steps = [
        gated("spec", "spec", "SPEC", []),
        plain("plan", "plan", "PLAN", ["SPEC"]),
    ]
    contents = {"spec": [md(GOOD_SPEC), md(GOOD_SPEC)], "plan": [md(GOOD_PLAN)]}
    harness = Harness(steps, replies=[rc_reply(), RESOLVED_REPLY], contents=contents)
    run = harness.start()
    run = harness.drive(run.id)
    assert run.state.stage == "COMPLETED"
    assert run.state.revisions.get("spec") == 1
    spec_requests = harness.requests["spec"]
    assert len(spec_requests) == 2
    feedback = spec_requests[1].feedback
    assert len(feedback) == 1
    assert feedback[0].reviewer == "ai-reviewer"
    assert "[F-001][BLOCKER][TRACEABILITY]" in feedback[0].comment
    assert "REQ-2" in feedback[0].comment
    assert run.artifacts["SPEC"].version == "2"
    completed = harness.events(run.id, "AI_REVIEW_COMPLETED")
    assert [event.metadata["verdict"] for event in completed] == [
        "REQUEST_CHANGES",
        "APPROVE",
    ]


def test_exhaustion_escalates_with_max_revisions_reason_and_resume_works() -> None:
    steps = [gated("spec", "spec", "SPEC", [], max_revisions=1)]
    contents = {"spec": [md(GOOD_SPEC), md(GOOD_SPEC), md(GOOD_SPEC)]}
    replies = [rc_reply(), rc_reply("STILL_OPEN"), APPROVE_REPLY]
    harness = Harness(steps, replies=replies, contents=contents)
    run = harness.start()
    run = harness.drive(run.id)
    assert run.state.stage == "SPEC_ESCALATED"
    escalated = harness.events(run.id, "WORKFLOW_ESCALATED")
    assert escalated and escalated[-1].metadata["reason"] == "MAX_REVISIONS"
    harness.engine.resume(run.id, reason="operator takes over")
    run = harness.drive(run.id)
    assert run.state.stage == "COMPLETED"
    assert len(harness.gateway.requests) == 3


def test_accept_with_warnings_continues_at_exhaustion() -> None:
    steps = [gated("spec", "spec", "SPEC", [], max_revisions=1)]
    contents = {"spec": [md(GOOD_SPEC), md(GOOD_SPEC)]}
    harness = Harness(steps, replies=[rc_reply(), rc_reply("STILL_OPEN")], contents=contents)
    context = {"approval": {"overrides": {"onExhausted": "accept_with_warnings"}}}
    run = harness.start(context=context)
    run = harness.drive(run.id)
    assert run.state.stage == "COMPLETED"
    assert harness.events(run.id, "AI_REVIEW_ACCEPTED_WITH_WARNINGS")
    decisions = harness.decisions()
    assert decisions[-1].decision == "APPROVED"
    assert "accepted with warnings" in decisions[-1].comment
    assert "F-001" in decisions[-1].comment


def test_stagnation_escalates_no_progress_on_a_trivial_edit() -> None:
    trivial = GOOD_SPEC.replace("Build a calculator.", "Build a calculator!")
    steps = [gated("spec", "spec", "SPEC", [], max_revisions=3)]
    contents = {"spec": [md(GOOD_SPEC), md(trivial)]}
    harness = Harness(steps, replies=[rc_reply(), rc_reply("STILL_OPEN")], contents=contents)
    run = harness.start()
    run = harness.drive(run.id)
    assert run.state.stage == "SPEC_ESCALATED"
    assert run.state.revisions.get("spec") == 3
    assert harness.events(run.id, "AI_REVIEW_STAGNATION")
    escalated = harness.events(run.id, "WORKFLOW_ESCALATED")
    assert escalated and escalated[-1].metadata["reason"] == "NO_PROGRESS"


def test_mechanical_blocker_short_circuits_the_model() -> None:
    broken = GOOD_SPEC.replace("## Open questions\nNone.\n", "")
    steps = [gated("spec", "spec", "SPEC", [])]
    contents = {"spec": [md(broken), md(GOOD_SPEC)]}
    harness = Harness(steps, replies=[APPROVE_REPLY], contents=contents)
    run = harness.start()
    run = harness.drive(run.id)
    assert run.state.stage == "COMPLETED"
    # Round 1 was mechanical-only (no queued reply consumed); the one
    # gateway call is round 2's AI review of the fixed artifact.
    assert len(harness.gateway.requests) == 1
    feedback = harness.requests["spec"][1].feedback
    assert "[M-001][BLOCKER][COMPLETENESS]" in feedback[0].comment


def test_reviewer_failure_retries_once_then_escalates_reviewer_failed() -> None:
    steps = [gated("spec", "spec", "SPEC", [])]
    harness = Harness(steps, replies=["not json", "still not json"], contents=full_contents())
    run = harness.start()
    harness.engine.tick(run.id)  # producer -> SPEC_REVIEW
    harness.engine.tick(run.id)  # review attempt 1 fails -> retry scheduled
    run = harness.engine.get(run.id)
    assert run.state.stage == "SPEC_REVIEW"
    assert run.retry_at is not None
    harness.clock.advance(10)
    harness.engine.tick(run.id)  # review attempt 2 fails -> escalate
    run = harness.engine.get(run.id)
    assert run.state.stage == "SPEC_ESCALATED"
    escalated = harness.events(run.id, "WORKFLOW_ESCALATED")
    assert escalated and escalated[-1].metadata["reason"] == "REVIEWER_FAILED"
    assert all(d.decision != "APPROVED" for d in harness.decisions())


class _RaisingModels:
    """A models gateway whose every call fails with one fixed error."""

    def __init__(self, error: ModelGatewayError) -> None:
        self._error = error

    def complete(self, request: Any) -> Any:
        raise self._error


def _drive_reviewer_failure(harness: Harness) -> WorkflowExecution:
    run = harness.start()
    harness.engine.tick(run.id)  # producer -> SPEC_REVIEW
    harness.engine.tick(run.id)  # review attempt 1 fails -> retry scheduled
    harness.clock.advance(10)
    harness.engine.tick(run.id)  # review attempt 2 fails -> escalate
    return harness.engine.get(run.id)


def test_reviewer_gateway_failure_escalates_with_the_cause_on_the_event() -> None:
    message = (
        "The provider rejected the request after several retries in the "
        "regional endpoint pool. Details: password = 'sup3rsecretvalue9' "
        "was echoed; the call used bearer abcdefghijklmnopqrstuvwxyz123456 "
        "against https://deploy:hunter2pass9@ci.internal.example/v1/models."
    )
    steps = [gated("spec", "spec", "SPEC", [])]
    harness = Harness(
        steps,
        replies=[],
        contents=full_contents(),
        gateway_wrapper=lambda _inner: _RaisingModels(
            ModelGatewayError("LLM_MODEL_NOT_SUPPORTED", message)
        ),
    )
    run = _drive_reviewer_failure(harness)
    assert run.state.stage == "SPEC_ESCALATED"
    escalated = harness.events(run.id, "WORKFLOW_ESCALATED")
    assert escalated and escalated[-1].metadata["reason"] == "REVIEWER_FAILED"
    assert escalated[-1].message == "AI review of Spec escalated: REVIEWER_FAILED"
    metadata = escalated[-1].metadata
    assert metadata["errorCode"] == "LLM_MODEL_NOT_SUPPORTED"
    assert "[REDACTED]" in metadata["errorMessage"]
    assert len(metadata["errorMessage"]) <= 240
    blob = json.dumps(escalated[-1].model_dump(mode="json"))
    for secret in ("sup3rsecretvalue9", "abcdefghijklmnopqrstuvwxyz123456", "hunter2pass9"):
        assert secret not in blob


def test_reviewer_invalid_reply_escalates_with_its_error_code() -> None:
    steps = [gated("spec", "spec", "SPEC", [])]
    harness = Harness(steps, replies=["not json", "still not json"], contents=full_contents())
    run = _drive_reviewer_failure(harness)
    assert run.state.stage == "SPEC_ESCALATED"
    escalated = harness.events(run.id, "WORKFLOW_ESCALATED")
    assert escalated and escalated[-1].metadata["reason"] == "REVIEWER_FAILED"
    assert escalated[-1].metadata["errorCode"] == "LLM_INVALID_RESPONSE"
    assert escalated[-1].metadata["errorMessage"]


def test_short_error_message_redacts_before_capping() -> None:
    # The token starts early enough that capping first would leave an
    # 18-char fragment — below the bearer pattern's 20-char threshold,
    # so a later redaction would miss it and the fragment would leak.
    message = "x" * 213 + " bearer abcdefghijklmnopqrstuvwxyz123456 trailing"
    error = PlatformError(
        code="LLM_TIMEOUT", message=message, category="LLM", retryable=True, timestamp=START
    )
    short = _short_error_message(error)
    assert len(short) <= 240
    assert "[REDACTED]" in short
    assert "abcdefghijklmnopqr" not in short


def test_other_escalation_events_carry_no_error_cause() -> None:
    steps = [gated("spec", "spec", "SPEC", [], max_revisions=1)]
    contents = {"spec": [md(GOOD_SPEC), md(GOOD_SPEC)]}
    harness = Harness(steps, replies=[rc_reply(), rc_reply()], contents=contents)
    run = harness.start()
    run = harness.drive(run.id)
    assert run.state.stage == "SPEC_ESCALATED"
    escalated = harness.events(run.id, "WORKFLOW_ESCALATED")
    assert escalated and escalated[-1].metadata["reason"] == "MAX_REVISIONS"
    assert "errorCode" not in escalated[-1].metadata
    assert "errorMessage" not in escalated[-1].metadata

    steps = [
        gated("spec", "spec", "SPEC", []),
        gated("plan", "plan", "PLAN", ["SPEC"]),
    ]
    contents = {"spec": [md(GOOD_SPEC)], "plan": [md(GOOD_PLAN)]}
    harness = Harness(steps, replies=[APPROVE_REPLY], contents=contents)
    run = harness.start(context={"approval": {"maxReviewRounds": 1}})
    run = harness.drive(run.id)
    assert run.state.stage == "PLAN_ESCALATED"
    escalated = harness.events(run.id, "WORKFLOW_ESCALATED")
    assert escalated and escalated[-1].metadata["reason"] == "BUDGET"
    assert "errorCode" not in escalated[-1].metadata
    assert "errorMessage" not in escalated[-1].metadata

    trivial = GOOD_SPEC.replace("Build a calculator.", "Build a calculator!")
    steps = [gated("spec", "spec", "SPEC", [], max_revisions=3)]
    contents = {"spec": [md(GOOD_SPEC), md(trivial)]}
    harness = Harness(steps, replies=[rc_reply(), rc_reply("STILL_OPEN")], contents=contents)
    run = harness.start()
    run = harness.drive(run.id)
    assert run.state.stage == "SPEC_ESCALATED"
    escalated = harness.events(run.id, "WORKFLOW_ESCALATED")
    assert escalated and escalated[-1].metadata["reason"] == "NO_PROGRESS"
    assert "errorCode" not in escalated[-1].metadata
    assert "errorMessage" not in escalated[-1].metadata


def test_review_round_budget_escalates_with_budget_reason() -> None:
    steps = [
        gated("spec", "spec", "SPEC", []),
        gated("plan", "plan", "PLAN", ["SPEC"]),
    ]
    contents = {"spec": [md(GOOD_SPEC)], "plan": [md(GOOD_PLAN)]}
    harness = Harness(steps, replies=[APPROVE_REPLY], contents=contents)
    run = harness.start(context={"approval": {"maxReviewRounds": 1}})
    run = harness.drive(run.id)
    assert run.state.stage == "PLAN_ESCALATED"
    escalated = harness.events(run.id, "WORKFLOW_ESCALATED")
    assert escalated and escalated[-1].metadata["reason"] == "BUDGET"
    assert len(harness.gateway.requests) == 1


def test_a_decision_landing_during_review_wins_over_the_reviewer() -> None:
    steps = [gated("spec", "spec", "SPEC", []), plain("plan", "plan", "PLAN", ["SPEC"])]
    contents = {"spec": [md(GOOD_SPEC)], "plan": [md(GOOD_PLAN)]}
    holder: dict[str, Any] = {}

    def decide_first(gateway: ScriptedModelGateway) -> Any:
        class Wrapper:
            requests = gateway.requests

            def complete(self, request: Any) -> Any:
                harness = holder["harness"]
                run = harness.engine.get(holder["run_id"])
                service = holder["service"]
                service.decide(
                    ApprovalDecision(
                        approval_id=run.approval_id or "",
                        reviewer="ai-reviewer",
                        decision="APPROVED",
                        comment="Decided while the reviewer was running",
                        created_at=harness.clock(),
                    )
                )
                return gateway.complete(request)

        return Wrapper()

    harness = Harness(steps, replies=[rc_reply()], contents=contents, gateway_wrapper=decide_first)
    holder["harness"] = harness
    holder["service"] = ApprovalService(harness.repo, id_factory=lambda: "unused")
    run = harness.start()
    holder["run_id"] = run.id
    run = harness.drive(run.id)
    assert run.state.stage == "COMPLETED"
    decisions = harness.decisions()
    assert len(decisions) == 1
    assert decisions[0].decision == "APPROVED"
    assert decisions[0].comment == "Decided while the reviewer was running"


def test_crash_between_claim_and_commit_does_not_double_count_the_round() -> None:
    store = InMemoryStore()
    steps = [gated("spec", "spec", "SPEC", []), plain("plan", "plan", "PLAN", ["SPEC"])]
    contents = {"spec": [md(GOOD_SPEC)], "plan": [md(GOOD_PLAN)]}
    harness = Harness(steps, replies=[APPROVE_REPLY], contents=contents, store=store)
    run = harness.start()
    harness.engine.tick(run.id)
    assert harness.engine.get(run.id).state.stage == "SPEC_REVIEW"
    wedged = store.get_execution(run.id)
    assert wedged is not None
    wedged.in_flight = "crashed-claim"
    store.save_execution(wedged)
    with pytest.raises(ValueError, match="Interrupted dispatch"):
        harness.engine.tick(run.id)
    harness.engine.recover(run.id, reason="restart after crash", retry_interrupted=True)
    run = harness.drive(run.id)
    assert run.state.stage == "COMPLETED"
    reviews = [a for a in run.artifact_history.values() if a.type == "ARTIFACT_REVIEW"]
    assert len(reviews) == 1
    assert len(harness.decisions()) == 1
    assert len(harness.gateway.requests) == 1


def test_unreadable_previous_review_emits_degraded_and_still_completes() -> None:
    store = InMemoryStore()
    steps = [gated("spec", "spec", "SPEC", [])]
    contents = {"spec": [md(GOOD_SPEC), md(GOOD_SPEC)]}
    harness = Harness(steps, replies=[rc_reply(), APPROVE_REPLY], contents=contents, store=store)
    run = harness.start()
    harness.engine.tick(run.id)  # producer
    harness.engine.tick(run.id)  # round 1: REQUEST_CHANGES
    harness.engine.tick(run.id)  # producer revision -> SPEC_REVIEW again
    stored = store.get_execution(run.id)
    assert stored is not None
    history = dict(stored.artifact_history)
    for artifact_id, artifact in history.items():
        if artifact.type == "ARTIFACT_REVIEW":
            history[artifact_id] = artifact.model_copy(update={"content": {"review": {"x": 1}}})
    stored.artifact_history = history
    store.save_execution(stored)
    run = harness.drive(run.id)
    assert run.state.stage == "COMPLETED"
    degraded = harness.events(run.id, "AI_REVIEW_DEGRADED")
    assert degraded and degraded[0].metadata["stage"] == "spec"


def test_human_mode_parks_exactly_as_before() -> None:
    steps = [gated("spec", "spec", "SPEC", [], mode="human")]
    harness = Harness(steps, replies=[], contents={"spec": [md(GOOD_SPEC)]})
    run = harness.start()
    run = harness.drive(run.id)
    assert run.state.stage == "SPEC_REVIEW"
    assert harness.gateway.requests == []
    requests = harness.approval_requests()
    assert len(requests) == 1
    assert requests[0].reviewers == ["dashboard"]
    decided = harness.engine.decide(run.id, reviewer="dashboard", decision="APPROVED", comment="ok")
    assert decided.state.stage == "COMPLETED"


def test_mode_none_skips_the_gate_without_a_request() -> None:
    steps = [gated("spec", "spec", "SPEC", []), plain("plan", "plan", "PLAN", ["SPEC"])]
    contents = {"spec": [md(GOOD_SPEC)], "plan": [md(GOOD_PLAN)]}
    harness = Harness(steps, replies=[], contents=contents)
    run = harness.start(context={"approval": {"overrides": {"mode": "none"}}})
    run = harness.drive(run.id)
    assert run.state.stage == "COMPLETED"
    assert harness.approval_requests() == []
    assert harness.events(run.id, "APPROVAL_SKIPPED")


def test_profile_policy_and_ai_policy_reach_the_request() -> None:
    human = Harness(
        [gated("spec", "spec", "SPEC", [], mode="human")],
        replies=[],
        contents={"spec": [md(GOOD_SPEC)]},
    )
    context = {
        "approval": {
            "overrides": {"mode": "human", "reviewers": ["alice"]},
            "policy": {"reviewers": ["alice"], "minApprovals": 1, "expiresInSeconds": None},
        }
    }
    run = human.start(context=context)
    run = human.drive(run.id)
    assert run.state.stage == "SPEC_REVIEW"
    assert human.approval_requests()[0].reviewers == ["alice"]

    ai_steps = [gated("spec", "spec", "SPEC", [])]
    ai = Harness(ai_steps, replies=[APPROVE_REPLY], contents=full_contents())
    ai_context = {
        "approval": {
            "overrides": {"reviewers": ["alice"]},
            "policy": {"reviewers": ["alice"], "minApprovals": 1, "expiresInSeconds": None},
        }
    }
    run = ai.start(context=ai_context)
    ai.drive(run.id)
    # An ai-mode step's request is addressed to the AI reviewer first,
    # then the profile's human reviewers (who may override manually).
    assert ai.approval_requests()[0].reviewers == ["ai-reviewer", "alice"]
    assert ai.approval_requests()[0].min_approvals == 1


def test_human_approve_on_an_ai_gate_advances_without_a_reviewer_call() -> None:
    steps = [gated("spec", "spec", "SPEC", []), plain("plan", "plan", "PLAN", ["SPEC"])]
    contents = {"spec": [md(GOOD_SPEC)], "plan": [md(GOOD_PLAN)]}
    harness = Harness(steps, replies=[APPROVE_REPLY], contents=contents)
    run = harness.start()
    harness.engine.tick(run.id)
    assert harness.engine.get(run.id).state.stage == "SPEC_REVIEW"
    harness.engine.decide(
        run.id,
        reviewer="dashboard",
        decision="APPROVED",
        comment="Read it myself; ship it.",
    )
    run = harness.drive(run.id)
    assert run.state.stage == "COMPLETED"
    assert harness.gateway.requests == []
    decisions = harness.decisions()
    assert len(decisions) == 1
    assert decisions[0].reviewer == "dashboard"
    assert decisions[0].reviewer_kind == "HUMAN"
    assert decisions[0].decision == "APPROVED"


def test_human_reject_on_an_ai_gate_revises_with_the_human_comment() -> None:
    steps = [gated("spec", "spec", "SPEC", []), plain("plan", "plan", "PLAN", ["SPEC"])]
    contents = {"spec": [md(GOOD_SPEC)], "plan": [md(GOOD_PLAN)]}
    harness = Harness(steps, replies=[APPROVE_REPLY], contents=contents)
    run = harness.start()
    harness.engine.tick(run.id)
    harness.engine.decide(
        run.id,
        reviewer="dashboard",
        decision="REQUEST_CHANGES",
        comment="Tighten the REQ-2 acceptance criteria.",
    )
    run = harness.drive(run.id)
    assert run.state.stage == "COMPLETED"
    feedback = harness.requests["spec"][1].feedback
    assert any(
        item.reviewer == "dashboard" and "Tighten the REQ-2" in item.comment for item in feedback
    )
    decisions = harness.decisions()
    human = [d for d in decisions if d.reviewer_kind == "HUMAN"]
    assert len(human) == 1 and human[0].decision == "REQUEST_CHANGES"
    assert any(d.reviewer == "ai-reviewer" and d.decision == "APPROVED" for d in decisions)
    assert len(harness.gateway.requests) == 1


def test_reviewer_result_after_a_human_reject_stands_down() -> None:
    steps = [gated("spec", "spec", "SPEC", []), plain("plan", "plan", "PLAN", ["SPEC"])]
    contents = {"spec": [md(GOOD_SPEC)], "plan": [md(GOOD_PLAN)]}
    holder: dict[str, Any] = {}

    def decide_first(gateway: ScriptedModelGateway) -> Any:
        class Wrapper:
            requests = gateway.requests

            def complete(self, request: Any) -> Any:
                if not holder.get("decided"):
                    holder["decided"] = True
                    harness = holder["harness"]
                    run = harness.engine.get(holder["run_id"])
                    holder["service"].decide(
                        ApprovalDecision(
                            approval_id=run.approval_id or "",
                            reviewer="dashboard",
                            decision="REQUEST_CHANGES",
                            comment="Human veto: the scope is wrong.",
                            created_at=harness.clock(),
                        )
                    )
                return gateway.complete(request)

        return Wrapper()

    harness = Harness(
        steps,
        replies=[rc_reply(), RESOLVED_REPLY],
        contents=contents,
        gateway_wrapper=decide_first,
    )
    holder["harness"] = harness
    holder["service"] = ApprovalService(harness.repo, id_factory=lambda: "unused")
    run = harness.start()
    holder["run_id"] = run.id
    run = harness.drive(run.id)
    assert run.state.stage == "COMPLETED"
    first = harness.approval_requests()[0]
    first_decisions = harness.repo.list_decisions(first.id)
    assert len(first_decisions) == 1
    assert first_decisions[0].reviewer == "dashboard"
    assert first_decisions[0].reviewer_kind == "HUMAN"
    feedback = harness.requests["spec"][1].feedback
    assert any("Human veto" in item.comment for item in feedback)


def test_approve_anyway_advances_an_escalated_gate_with_a_human_decision() -> None:
    steps = [
        gated("spec", "spec", "SPEC", [], max_revisions=1),
        plain("plan", "plan", "PLAN", ["SPEC"]),
    ]
    contents = {"spec": [md(GOOD_SPEC)], "plan": [md(GOOD_PLAN)]}
    harness = Harness(steps, replies=[rc_reply(), rc_reply()], contents=contents)
    run = harness.drive(harness.start().id)
    assert run.state.stage == "SPEC_ESCALATED"
    artifact_id = harness.engine.get(run.id).artifacts["SPEC"].id
    run = approve_anyway(
        harness.engine, run.id, reviewer="dashboard", comment="Business accepted the risk."
    )
    assert run.state.stage == "PLAN"
    run = harness.drive(run.id)
    assert run.state.stage == "COMPLETED"
    requests = harness.approval_requests()
    assert len(requests) == 3
    override = requests[2]
    assert override.artifact_id == artifact_id
    assert override.status == "APPROVED"
    decisions = harness.repo.list_decisions(override.id)
    assert len(decisions) == 1
    assert decisions[0].reviewer == "dashboard"
    assert decisions[0].reviewer_kind == "HUMAN"
    assert decisions[0].comment == "Business accepted the risk."
    assert harness.events(run.id, "APPROVAL_APPROVED_ANYWAY")


def test_approve_anyway_requires_an_escalated_gate() -> None:
    steps = [gated("spec", "spec", "SPEC", []), plain("plan", "plan", "PLAN", ["SPEC"])]
    contents = {"spec": [md(GOOD_SPEC)], "plan": [md(GOOD_PLAN)]}
    harness = Harness(steps, replies=[APPROVE_REPLY], contents=contents)
    run = harness.start()
    harness.engine.tick(run.id)
    assert harness.engine.get(run.id).state.stage == "SPEC_REVIEW"
    with pytest.raises(InvalidTransition):
        approve_anyway(harness.engine, run.id, reviewer="dashboard", comment="Too early.")


def test_approve_anyway_works_on_a_pre_phase12_pinned_definition() -> None:
    pinned = WorkflowDefinition.model_validate(
        {
            "id": "development",
            "name": "Development",
            "version": "1",
            "steps": [
                {
                    "id": "spec",
                    "name": "Spec",
                    "type": "AGENT",
                    "stage": "SPEC",
                    "agentType": "spec",
                    "requiresApproval": True,
                    "consumes": [],
                    "produces": ["SPEC"],
                },
                {
                    "id": "plan",
                    "name": "Plan",
                    "type": "AGENT",
                    "stage": "PLAN",
                    "agentType": "plan",
                    "requiresApproval": False,
                    "consumes": ["SPEC"],
                    "produces": ["PLAN"],
                },
            ],
        }
    )
    steps = [plain("spec", "spec", "SPEC", []), plain("plan", "plan", "PLAN", ["SPEC"])]
    contents = {"spec": [md(GOOD_SPEC)], "plan": [md(GOOD_PLAN)]}
    harness = Harness(steps, replies=[], contents=contents, definition=pinned)
    run = harness.start()
    for _ in range(4):
        harness.drive(run.id)
        run = harness.engine.get(run.id)
        if run.state.stage.endswith("_ESCALATED"):
            break
        harness.engine.decide(
            run.id, reviewer="dashboard", decision="REQUEST_CHANGES", comment="Not yet."
        )
    harness.drive(run.id)
    run = harness.engine.get(run.id)
    assert run.state.stage == "SPEC_ESCALATED"
    run = approve_anyway(harness.engine, run.id, reviewer="dashboard", comment="Ship it.")
    run = harness.drive(run.id)
    assert run.state.stage == "COMPLETED"


def test_resume_guidance_reaches_the_producer_as_feedback() -> None:
    steps = [
        gated("spec", "spec", "SPEC", [], max_revisions=1),
        plain("plan", "plan", "PLAN", ["SPEC"]),
    ]
    contents = {"spec": [md(GOOD_SPEC)], "plan": [md(GOOD_PLAN)]}
    harness = Harness(steps, replies=[rc_reply(), rc_reply(), RESOLVED_REPLY], contents=contents)
    run = harness.drive(harness.start().id)
    assert run.state.stage == "SPEC_ESCALATED"
    harness.engine.resume(run.id, reason="operator resume")
    deliver_guidance(harness.engine, run.id, guidance="Focus on REQ-2 only.", operator="dashboard")
    run = harness.drive(run.id)
    assert run.state.stage == "COMPLETED"
    feedback = harness.requests["spec"][-1].feedback
    assert any(
        item.reviewer == "dashboard" and item.comment == "Focus on REQ-2 only." for item in feedback
    )
