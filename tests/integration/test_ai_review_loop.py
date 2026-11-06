"""Phase 12 Stage C integration: the AI review loop end to end.

Covers the three levels the unit tests cannot: the REAL spec agent
receiving reviewer findings in its prompt, a run started from a real
project profile honouring the profile's approval mode and reviewers,
and orphan adoption resuming AI-review stages (but not human gates
or escalations) after a restart.
"""

from __future__ import annotations

import time
from contextlib import suppress
from datetime import UTC, datetime
from itertools import count
from pathlib import Path
from typing import Any

from asf.agents.artifact_review import ArtifactReviewAgent, ArtifactReviewSettings
from asf.agents.base import AgentRuntime
from asf.agents.loading import load_artifact_review_prompts
from asf.agents.spec.factory import build_spec_agent
from asf.api.service import FactoryService
from asf.api.service.escalation_ops import approve_escalated_run
from asf.api.service.reviews_view import run_reviews
from asf.approval.models import ApprovalPolicy
from asf.approval.service import ApprovalService
from asf.configuration.platform import PlatformConfig
from asf.configuration.project import ProjectProfile
from asf.contracts.models import AgentMetadata, Artifact, ModelRequest, ModelResponse
from asf.models.fake import ScriptedModelGateway
from asf.orchestrator import AgentRegistry, Orchestrator
from asf.storage.memory import InMemoryApprovalRepository
from asf.workflow.definition import WorkflowDefinition
from tests.unit.test_agent_base import DummyAgent
from tests.unit.test_ai_review_stage import (
    APPROVE_REPLY,
    RESOLVED_REPLY,
    Harness,
    gated,
    md,
    plain,
    rc_reply,
)
from tests.unit.test_artifact_review_checks import GOOD_PLAN, GOOD_SPEC

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = REPO_ROOT / "templates"
NOW = datetime(2026, 1, 1, tzinfo=UTC)


class RecordingGateway:
    """Scripted gateway that keeps the requests it was called with."""

    def __init__(self, replies: list[str]) -> None:
        self._inner = ScriptedModelGateway(replies)
        self.requests: list[ModelRequest] = []

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return self._inner.complete(request)


def test_real_spec_agent_receives_the_findings_in_its_prompt() -> None:
    ids = count(1)

    def new_id() -> str:
        return f"id-{next(ids)}"

    def clock() -> datetime:
        return NOW

    spec_gateway = RecordingGateway([GOOD_SPEC, GOOD_SPEC])
    spec_runtime = AgentRuntime(models=spec_gateway, clock=clock, new_id=new_id)
    reviewer_runtime = AgentRuntime(
        models=ScriptedModelGateway([rc_reply(), RESOLVED_REPLY]),
        clock=clock,
        new_id=new_id,
    )
    registry = AgentRegistry()
    registry.register(build_spec_agent(spec_runtime, PlatformConfig(), TEMPLATES_DIR))
    registry.register(
        ArtifactReviewAgent(
            reviewer_runtime, ArtifactReviewSettings(prompts=load_artifact_review_prompts())
        )
    )

    def produce_plan(request: Any) -> tuple[dict[str, Any], list[Artifact]]:
        artifact = Artifact(
            id=f"art-{next(ids)}",
            type="PLAN",
            name="PLAN",
            version="1",
            content=md(GOOD_PLAN),
            created_by="agent-plan",
            created_at=NOW,
        )
        return {"summary": "done"}, [artifact]

    registry.register(
        DummyAgent(
            spec_runtime,
            metadata=AgentMetadata(
                id="agent-plan", name="plan", type="plan", version="1", status="IDLE"
            ),
            run_behavior=produce_plan,
        )
    )

    workflow = WorkflowDefinition(
        id="development",
        name="Development",
        version="1",
        steps=[gated("spec", "spec", "SPEC", []), plain("plan", "plan", "PLAN", ["SPEC"])],
    )
    engine = Orchestrator(
        workflow,
        registry,
        clock=clock,
        new_id=new_id,
        approvals=ApprovalService(InMemoryApprovalRepository(), id_factory=new_id),
        approval_policy=ApprovalPolicy(reviewers=["dashboard"]),
    )
    run = engine.start(
        task_id="task-1",
        project_id="project-1",
        inputs={"spec": {"requirement": "Build a calculator"}},
        context={"project": {"name": "example"}},
    )
    for _ in range(10):
        engine.tick(run.id)
        if engine.get(run.id).state.stage == "COMPLETED":
            break
    run = engine.get(run.id)
    assert run.state.stage == "COMPLETED"
    assert len(spec_gateway.requests) == 2
    revised_prompt = spec_gateway.requests[1].messages[-1].content
    assert "## Reviewer feedback" in revised_prompt
    assert "[REQUEST_CHANGES] ai-reviewer:" in revised_prompt
    assert "[F-001][BLOCKER][TRACEABILITY]" in revised_prompt
    assert run.artifacts["SPEC"].version == "2"


def _profile(project_id: str, approval: dict[str, Any]) -> ProjectProfile:
    return ProjectProfile(
        id=project_id,
        name=project_id,
        workflow="development",
        technology={},
        repository={},
        configuration={"approval": approval},
    )


def test_run_started_from_a_real_profile_honours_its_approval_mode() -> None:
    steps = [gated("spec", "spec", "SPEC", []), plain("plan", "plan", "PLAN", ["SPEC"])]
    contents = {"spec": [md(GOOD_SPEC)], "plan": [md(GOOD_PLAN)]}
    harness = Harness(steps, replies=[APPROVE_REPLY], contents=contents)
    projects = {
        "ai-proj": _profile("ai-proj", {"mode": "ai"}),
        "human-proj": _profile("human-proj", {"mode": "human", "reviewers": ["alice"]}),
    }
    service = FactoryService(
        harness.engine, projects=projects, clock=harness.clock, reviewer="alice"
    )
    ai_run = service.start_run("task-ai", "ai-proj", inputs={"spec": {"requirement": "x"}})
    service.wait_for_drives()
    ai_view = service.get_workflow(ai_run.id)
    assert ai_view is not None and ai_view["status"] == "COMPLETED"
    ai_requests = [r for r in harness.repo.list_by_task("task-ai")]
    assert ai_requests and ai_requests[0].reviewers == ["ai-reviewer", "dashboard"]

    human_run = service.start_run("task-human", "human-proj", inputs={"spec": {"requirement": "x"}})
    service.wait_for_drives()
    human_view = service.get_workflow(human_run.id)
    assert human_view is not None and human_view["status"] == "WAITING_APPROVAL"
    human_requests = harness.repo.list_by_task("task-human")
    assert human_requests and human_requests[0].reviewers == ["alice"]
    decided = service.decide_approval(human_requests[0].id, decision="APPROVE")
    assert decided is not None
    service.wait_for_drives()
    human_view = service.get_workflow(human_run.id)
    assert human_view is not None and human_view["status"] == "COMPLETED"


def test_adopt_orphans_resumes_ai_review_but_not_human_or_escalated() -> None:
    steps = [
        gated("spec", "spec", "SPEC", [], max_revisions=1),
        plain("plan", "plan", "PLAN", ["SPEC"]),
    ]
    contents = {"spec": [md(GOOD_SPEC)] * 3, "plan": [md(GOOD_PLAN)]}
    replies = [rc_reply(), rc_reply("STILL_OPEN"), APPROVE_REPLY]
    harness = Harness(steps, replies=replies, contents=contents)
    engine = harness.engine
    escalated = harness.start()
    harness.drive(escalated.id)
    assert engine.get(escalated.id).state.stage == "SPEC_ESCALATED"

    ai_run = engine.start(
        task_id="task-ai",
        project_id="project-1",
        inputs={"spec": {"requirement": "Build a calculator"}},
        context={"approval": {"overrides": {"mode": "ai"}}},
    )
    engine.tick(ai_run.id)
    assert engine.get(ai_run.id).state.stage == "SPEC_REVIEW"
    human_run = engine.start(
        task_id="task-human",
        project_id="project-1",
        inputs={"spec": {"requirement": "Build a calculator"}},
        context={"approval": {"overrides": {"mode": "human"}}},
    )
    engine.tick(human_run.id)
    assert engine.get(human_run.id).state.stage == "SPEC_REVIEW"

    service = FactoryService(engine, projects={}, clock=harness.clock)
    for run_id in (escalated.id, ai_run.id, human_run.id):
        service.track(run_id)
    service._adopt_orphans()
    service.wait_for_drives()
    assert engine.get(ai_run.id).state.stage == "COMPLETED"
    assert engine.get(human_run.id).state.stage == "SPEC_REVIEW"
    assert engine.get(escalated.id).state.stage == "SPEC_ESCALATED"


def _status_of(service: FactoryService, run_id: str) -> str | None:
    view = service.get_workflow(run_id)
    return view["status"] if view is not None else None


def _wait_for_status(service: FactoryService, run_id: str, status: str) -> None:
    # The runs cache (1.5s TTL) can lag the drive; poll briefly.
    for _ in range(60):
        if _status_of(service, run_id) == status:
            return
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} never reached {status}: {_status_of(service, run_id)}")


def _escalated_service(replies: list[str]) -> tuple[Harness, FactoryService, Any]:
    steps = [
        gated("spec", "spec", "SPEC", [], max_revisions=1),
        plain("plan", "plan", "PLAN", ["SPEC"]),
    ]
    contents = {"spec": [md(GOOD_SPEC)], "plan": [md(GOOD_PLAN)]}
    harness = Harness(steps, replies=replies, contents=contents)
    projects = {"ai-proj": _profile("ai-proj", {"mode": "ai", "reviewers": ["alice"]})}
    service = FactoryService(
        harness.engine, projects=projects, clock=harness.clock, reviewer="alice"
    )
    run = service.start_run("task-esc", "ai-proj", inputs={"spec": {"requirement": "x"}})
    service.wait_for_drives()
    _wait_for_status(service, run.id, "ESCALATED")
    return harness, service, run


def test_service_approve_escalation_approves_anyway_and_completes() -> None:
    harness, service, run = _escalated_service([rc_reply(), rc_reply()])
    view = approve_escalated_run(service, run.id, reason="Ship it as-is", operator="alice")
    assert view is not None
    service.wait_for_drives()
    _wait_for_status(service, run.id, "COMPLETED")
    requests = harness.repo.list_by_task("task-esc")
    override = requests[-1]
    assert override.status == "APPROVED"
    decisions = harness.repo.list_decisions(override.id)
    assert len(decisions) == 1
    assert decisions[0].reviewer == "alice"
    assert decisions[0].reviewer_kind == "HUMAN"
    assert decisions[0].comment == "Ship it as-is"


def test_service_resume_with_guidance_feeds_the_producer_and_completes() -> None:
    harness, service, run = _escalated_service([rc_reply(), rc_reply(), RESOLVED_REPLY])
    view = service.resume_escalation(
        run.id, reason="one more round", operator="alice", guidance="Focus on REQ-2 only."
    )
    assert view is not None
    service.wait_for_drives()
    _wait_for_status(service, run.id, "COMPLETED")
    feedback = harness.requests["spec"][-1].feedback
    assert any(
        item.reviewer == "alice" and item.comment == "Focus on REQ-2 only." for item in feedback
    )


def test_waiting_block_describes_an_escalated_gate() -> None:
    _harness, service, run = _escalated_service([rc_reply(), rc_reply()])
    view = service.get_workflow(run.id)
    assert view is not None
    waiting = view["waiting"]
    assert waiting["kind"] == "ESCALATED"
    assert waiting["escalationReason"] == "MAX_REVISIONS"
    assert waiting["openBlockers"] == 1
    assert waiting["suggestedActions"] == ["resume", "approve", "cancel"]


def test_waiting_block_describes_an_ai_review_in_progress() -> None:
    import threading

    gate = threading.Event()

    class BlockingGateway:
        def __init__(self, inner: Any) -> None:
            self._inner = inner
            self.requests = inner.requests

        def complete(self, request: Any) -> Any:
            gate.wait(timeout=30)
            return self._inner.complete(request)

    steps = [
        gated("spec", "spec", "SPEC", [], max_revisions=4),
        plain("plan", "plan", "PLAN", ["SPEC"]),
    ]
    contents = {"spec": [md(GOOD_SPEC)], "plan": [md(GOOD_PLAN)]}
    harness = Harness(
        steps, replies=[APPROVE_REPLY], contents=contents, gateway_wrapper=BlockingGateway
    )
    projects = {"ai-proj": _profile("ai-proj", {"mode": "ai"})}
    service = FactoryService(
        harness.engine, projects=projects, clock=harness.clock, reviewer="alice"
    )
    run = service.start_run("task-wait", "ai-proj", inputs={"spec": {"requirement": "x"}})
    try:
        for _ in range(100):
            view = service.get_workflow(run.id)
            if view is not None and view["status"] == "AI_REVIEWING":
                break
            time.sleep(0.05)
        assert view is not None and view["status"] == "AI_REVIEWING"
        waiting = view["waiting"]
        assert waiting["kind"] == "AI_REVIEW"
        assert waiting["stage"] == "SPEC"
        assert waiting["round"] == 1
        assert waiting["maxRounds"] == 4
        assert waiting["suggestedActions"] == ["approve", "reject", "cancel"]
    finally:
        gate.set()
    service.wait_for_drives()
    _wait_for_status(service, run.id, "COMPLETED")


def test_run_reviews_view_groups_rounds_per_stage() -> None:
    steps = [
        gated("spec", "spec", "SPEC", [], max_revisions=3),
        plain("plan", "plan", "PLAN", ["SPEC"]),
    ]
    contents = {"spec": [md(GOOD_SPEC)], "plan": [md(GOOD_PLAN)]}
    harness = Harness(steps, replies=[rc_reply(), RESOLVED_REPLY], contents=contents)
    projects = {"ai-proj": _profile("ai-proj", {"mode": "ai"})}
    service = FactoryService(
        harness.engine, projects=projects, clock=harness.clock, reviewer="alice"
    )
    run = service.start_run("task-rev", "ai-proj", inputs={"spec": {"requirement": "x"}})
    service.wait_for_drives()
    _wait_for_status(service, run.id, "COMPLETED")
    view = run_reviews(service, run.id)
    assert view is not None and view["runId"] == run.id
    assert [stage["stage"] for stage in view["stages"]] == ["spec"]
    rounds = view["stages"][0]["rounds"]
    assert [item["round"] for item in rounds] == [1, 2]
    assert [item["verdict"] for item in rounds] == ["REQUEST_CHANGES", "APPROVE"]
    first = rounds[0]
    assert first["counts"]["BLOCKER"] == 1
    assert first["reviewedArtifactVersion"] == "1"
    finding = first["findings"][0]
    assert finding["id"] == "F-001"
    assert finding["requiredChange"] == "Add an acceptance criterion for REQ-2."
    assert run_reviews(service, "no-such-run") is None


def test_manual_ticks_never_double_dispatch_a_reviewer_round() -> None:
    import threading

    entered = threading.Event()
    release = threading.Event()

    class FirstCallBlockingGateway:
        """Blocks the first reviewer call; counts every dispatch."""

        def __init__(self, inner: Any) -> None:
            self._inner = inner
            self.requests = inner.requests
            self.calls = 0

        def complete(self, request: Any) -> Any:
            self.calls += 1
            if self.calls == 1:
                entered.set()
                release.wait(timeout=30)
            return self._inner.complete(request)

    holder: dict[str, Any] = {}

    def wrap(inner: Any) -> Any:
        holder["gateway"] = FirstCallBlockingGateway(inner)
        return holder["gateway"]

    steps = [
        gated("spec", "spec", "SPEC", [], max_revisions=4),
        plain("plan", "plan", "PLAN", ["SPEC"]),
    ]
    contents = {"spec": [md(GOOD_SPEC)], "plan": [md(GOOD_PLAN)]}
    harness = Harness(steps, replies=[APPROVE_REPLY], contents=contents, gateway_wrapper=wrap)
    projects = {"ai-proj": _profile("ai-proj", {"mode": "ai"})}
    service = FactoryService(
        harness.engine, projects=projects, clock=harness.clock, reviewer="alice"
    )
    run = service.start_run("task-race", "ai-proj", inputs={"spec": {"requirement": "x"}})
    try:
        # The background driver claims round 1 and blocks inside the
        # reviewer call, holding the run's in-flight token.
        assert entered.wait(timeout=10), "background driver never dispatched the reviewer"
        gateway = holder["gateway"]
        assert gateway.calls == 1
        # Manual ticks (the endpoint path) while round 1 is in
        # flight: they may be rejected by the claim guard, but they
        # must never dispatch a second reviewer call for the same
        # (run, stage, revision).
        for _ in range(3):
            with suppress(Exception):
                service.tick_run(run.id)
        assert gateway.calls == 1
    finally:
        release.set()
    service.wait_for_drives()
    _wait_for_status(service, run.id, "COMPLETED")
    assert gateway.calls == 1
    reviews = [
        item
        for item in harness.engine.get(run.id).artifact_history.values()
        if item.type == "ARTIFACT_REVIEW"
    ]
    assert len(reviews) == 1
    requests = harness.repo.list_by_task("task-race")
    assert len(harness.repo.list_decisions(requests[0].id)) == 1
