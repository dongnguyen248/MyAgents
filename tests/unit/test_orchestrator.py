from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import count

import pytest

from asf.agents.base import AgentRuntime
from asf.approval.errors import ApprovalError
from asf.approval.models import ApprovalPolicy
from asf.approval.service import ApprovalService
from asf.configuration.platform import RetryPolicySettings
from asf.contracts.models import AgentMetadata, Artifact
from asf.models.fake import ScriptedModelGateway
from asf.orchestrator import AgentRegistry, Orchestrator
from asf.state_machine.machine import InvalidTransition
from asf.storage.memory import InMemoryApprovalRepository
from asf.workflow.definition import WorkflowDefinition, WorkflowStepDef
from tests.unit.test_agent_base import DummyAgent

NOW = datetime(2026, 11, 2, tzinfo=UTC)


def step(name: str, *, approval: bool = False, revisions: int = 2) -> WorkflowStepDef:
    return WorkflowStepDef(
        id=name,
        name=name,
        type="AGENT",
        stage=name.upper(),
        agent_type=name,
        requires_approval=approval,
        max_revisions=revisions if approval else None,
        consumes=["SPEC"] if name == "plan" else [],
        produces=[name.upper()],
    )


def make_engine(
    *,
    approval: bool = False,
    revisions: int = 2,
    two_steps: bool = True,
) -> tuple[Orchestrator, DummyAgent, DummyAgent, InMemoryApprovalRepository]:
    ids = count(1)
    runtime = AgentRuntime(
        models=ScriptedModelGateway([]),
        clock=lambda: NOW,
        new_id=lambda: f"id-{next(ids)}",
    )

    def agent(name: str) -> DummyAgent:
        def produce(request):
            artifact = Artifact(
                id=f"art-{next(ids)}",
                type=name.upper(),
                name=name,
                version="1",
                content={"text": name},
                created_by=f"agent-{name}",
                created_at=NOW,
            )
            return {"summary": "done"}, [artifact]

        return DummyAgent(
            runtime,
            metadata=AgentMetadata(
                id=f"agent-{name}",
                name=name,
                type=name,
                version="1",
                status="IDLE",
            ),
            run_behavior=produce,
        )

    spec, plan = agent("spec"), agent("plan")
    registry = AgentRegistry()
    registry.register(spec)
    registry.register(plan)
    repo = InMemoryApprovalRepository()
    service = ApprovalService(repo, id_factory=runtime.new_id)
    workflow = WorkflowDefinition(
        id="development",
        name="Development",
        version="1",
        steps=[step("spec", approval=approval, revisions=revisions)]
        + ([step("plan")] if two_steps else []),
    )
    engine = Orchestrator(
        workflow,
        registry,
        clock=runtime.clock,
        new_id=runtime.new_id,
        approvals=service,
        approval_policy=ApprovalPolicy(reviewers=["reviewer"]),
    )
    return engine, spec, plan, repo


def start(engine: Orchestrator):
    return engine.start(
        task_id="task-1",
        project_id="project-1",
        inputs={"spec": {"requirement": "Add a feature"}},
        context={"project": {"name": "example"}},
    )


def test_registry_registration_lookup_and_metadata():
    _, spec, plan, _ = make_engine()
    registry = AgentRegistry()
    registry.register(spec)
    registry.register(plan)
    assert registry.get("agent-spec") is spec
    assert registry.for_type("plan") is plan
    assert [item.id for item in registry.list()] == ["agent-spec", "agent-plan"]
    metadata = registry.list()
    metadata[0].configuration["changed"] = True
    assert "changed" not in spec.metadata.configuration
    registry.unregister("agent-plan")
    with pytest.raises(KeyError):
        registry.get("agent-plan")


def test_registry_rejects_duplicate_id_and_type():
    _, spec, _, _ = make_engine()
    registry = AgentRegistry()
    registry.register(spec)
    with pytest.raises(ValueError):
        registry.register(spec)
    spec._metadata = spec.metadata.model_copy(update={"id": "other-id"})
    with pytest.raises(ValueError):
        registry.register(spec)


def test_dispatches_one_step_and_routes_only_consumed_artifacts():
    engine, spec, plan, _ = make_engine()
    received = []
    original = plan._run_behavior

    def record(request):
        received.append(request)
        return original(request)

    plan._run_behavior = record
    run = start(engine)
    assert run.state.stage == "SPEC"
    assert not spec.run_called
    run = engine.tick(run.id)
    assert run.state.stage == "PLAN"
    assert spec.run_called and not plan.run_called
    run = engine.tick(run.id)
    assert run.state.stage == "COMPLETED"
    assert [a.type for a in received[0].artifacts] == ["SPEC"]
    assert received[0].input == {}
    assert received[0].context["project"]["name"] == "example"
    assert received[0].workflow_id == "development"
    assert received[0].metadata["attempt"] == 1
    assert len(run.results) == 2
    assert run.errors == []
    with pytest.raises(InvalidTransition):
        engine.tick(run.id)


def test_approval_pauses_dispatch_and_uses_trusted_clock():
    engine, _, plan, repo = make_engine(approval=True)
    run = engine.tick(start(engine).id)
    assert run.state.stage == "SPEC_REVIEW"
    assert run.approval_id is not None
    assert repo.get(run.approval_id).artifact_id == run.artifacts["SPEC"].id
    assert engine.tick(run.id).state.stage == "SPEC_REVIEW"
    assert not plan.run_called
    with pytest.raises(ApprovalError) as exc:
        engine.decide(run.id, reviewer="outsider", decision="APPROVED")
    assert exc.value.code == "APPROVAL_NOT_AUTHORIZED"
    run = engine.decide(run.id, reviewer="reviewer", decision="APPROVED")
    assert run.state.stage == "PLAN"
    assert repo.list_decisions(repo.list_by_task("task-1")[0].id)[0].created_at == NOW
    assert not plan.run_called
    assert engine.tick(run.id).state.stage == "COMPLETED"


@pytest.mark.parametrize("decision", ["REJECTED", "REQUEST_CHANGES"])
def test_rejection_routes_feedback_and_previous_output_to_same_agent(decision):
    engine, spec, plan, _ = make_engine(approval=True)
    received = []
    original = spec._run_behavior

    def record(request):
        received.append(request)
        return original(request)

    spec._run_behavior = record
    run = engine.tick(start(engine).id)
    old_artifact = run.artifacts["SPEC"]
    run = engine.decide(run.id, reviewer="reviewer", decision=decision, comment="Clarify scope")
    assert run.state.stage == "SPEC_DRAFT"
    assert run.state.revisions["spec"] == 1
    run = engine.tick(run.id)
    assert run.state.stage == "SPEC_REVIEW"
    assert len(received) == 2
    assert received[1].artifacts == [old_artifact]
    assert received[1].feedback[0].comment == "Clarify scope"
    assert received[1].metadata["attempt"] == 2
    assert not plan.run_called


def test_skip_approval_advances_without_a_request():
    engine, spec, plan, repo = make_engine(approval=True)
    run = engine.start(
        task_id="task-1",
        project_id="project-1",
        inputs={"spec": {"requirement": "Add a feature"}},
        context={"project": {"name": "example"}, "skipApprovals": ["spec"]},
    )
    run = engine.tick(run.id)
    # The spec gate was never requested: the run went straight to the
    # plan step, with an audit event instead of an approval record.
    assert run.state.stage == "PLAN"
    assert run.approval_id is None
    assert repo.list_by_task("task-1") == []
    assert any(
        obs.event is not None and obs.event.event_type == "APPROVAL_SKIPPED"
        for obs in run.observations
    )
    run = engine.tick(run.id)
    assert run.state.stage == "COMPLETED"


def test_revision_limit_escalates_without_another_execution():
    engine, _, _, _ = make_engine(approval=True, revisions=0)
    run = engine.tick(start(engine).id)
    run = engine.decide(run.id, reviewer="reviewer", decision="REJECTED", comment="Revise")
    assert run.state.stage == "SPEC_ESCALATED"
    assert engine.tick(run.id).state.stage == "SPEC_ESCALATED"
    assert len(run.results) == 1


def test_partial_approval_does_not_advance():
    engine, _, _, _ = make_engine(approval=True)
    engine._approval_policy = ApprovalPolicy(reviewers=["one", "two"], min_approvals=2)
    run = engine.tick(start(engine).id)
    run = engine.decide(run.id, reviewer="one", decision="APPROVED")
    assert run.state.stage == "SPEC_REVIEW"
    run = engine.decide(run.id, reviewer="two", decision="APPROVED")
    assert run.state.stage == "PLAN"


def test_snapshots_and_runs_are_isolated():
    engine, _, _, _ = make_engine()
    first = start(engine)
    second = start(engine)
    first.context["project"]["name"] = "modified"
    first.inputs["spec"]["requirement"] = "modified"
    assert engine.get(first.id).context["project"]["name"] == "example"
    assert engine.get(first.id).inputs["spec"]["requirement"] == "Add a feature"
    engine.tick(first.id)
    assert engine.get(second.id).state.stage == "SPEC"
    assert engine.get(second.id).artifacts == {}
    with pytest.raises(KeyError):
        engine.get("unknown")


@pytest.mark.parametrize(
    "output",
    [
        {"verdict": "FAIL"},
        {"verdict": "CHANGES_REQUESTED"},
        {"verdict": "unknown"},
    ],
)
def test_quality_verdict_never_advances_to_next_step(output):
    engine, spec, plan, _ = make_engine()
    original = spec._run_behavior
    spec._run_behavior = lambda request: (output, original(request)[1])
    run = engine.tick(start(engine).id)
    assert run.state.stage == "FAILED"
    assert run.errors[0].code == "VALIDATION_FAILED"
    assert not plan.run_called


@pytest.mark.parametrize(
    "agent_type,verdict,expected_stage",
    [
        ("review", "APPROVE", "PLAN"),
        ("review", "PASS", "FAILED"),
        ("review", None, "FAILED"),
        ("test", "PASS", "PLAN"),
        ("test", "APPROVE", "FAILED"),
        ("test", None, "FAILED"),
    ],
)
def test_quality_verdict_must_match_the_specific_agent_contract(
    agent_type,
    verdict,
    expected_stage,
):
    engine, spec, plan, _ = make_engine()
    engine._registry.unregister(spec.metadata.id)
    spec._metadata = spec.metadata.model_copy(update={"type": agent_type})
    engine._registry.register(spec)
    engine._definition.steps[0] = engine._definition.steps[0].model_copy(
        update={"agent_type": agent_type},
    )
    original = spec._run_behavior
    spec._run_behavior = lambda request: ({"verdict": verdict}, original(request)[1])
    run = engine.tick(start(engine).id)
    assert run.state.stage == expected_stage
    assert not plan.run_called
    assert len(run.errors) == (0 if expected_stage == "PLAN" else 1)


def test_agent_failure_is_preserved_and_no_artifacts_are_published():
    engine, spec, plan, _ = make_engine()
    spec._run_behavior = RuntimeError("private diagnostic")
    run = engine.tick(start(engine).id)
    assert run.state.stage == "FAILED"
    assert run.errors[0].code == "AGENT_EXECUTION_FAILED"
    assert not plan.run_called
    assert run.artifacts == {}
    assert "private diagnostic" not in repr(run.errors)


@pytest.mark.parametrize("defect", ["missing", "extra", "duplicate", "wrong-creator"])
def test_success_with_invalid_artifact_contract_fails_closed(defect):
    engine, spec, plan, _ = make_engine()
    original = spec._run_behavior

    def broken(request):
        output, artifacts = original(request)
        if defect == "missing":
            artifacts = []
        elif defect == "extra":
            artifacts.append(artifacts[0].model_copy(update={"type": "OTHER"}))
        elif defect == "duplicate":
            artifacts.append(artifacts[0])
        else:
            artifacts[0] = artifacts[0].model_copy(update={"created_by": "someone-else"})
        return output, artifacts

    spec._run_behavior = broken
    run = engine.tick(start(engine).id)
    assert run.state.stage == "FAILED"
    assert run.errors[0].code == "VALIDATION_FAILED"
    assert run.artifacts == {}
    assert not plan.run_called


def test_missing_agent_and_unsupported_action_are_explicit_failures():
    engine, spec, _, _ = make_engine()
    engine._registry.unregister(spec.metadata.id)
    run = engine.tick(start(engine).id)
    assert run.state.stage == "FAILED"
    assert run.errors[0].code == "AGENT_NOT_REGISTERED"

    engine, _, _, _ = make_engine()
    engine._definition.steps[0] = engine._definition.steps[0].model_copy(
        update={"action": "run-pipeline", "agent_type": None},
    )
    run = engine.tick(start(engine).id)
    assert run.state.stage == "FAILED"
    assert run.errors[0].code == "INTEGRATION_UNAVAILABLE"


def test_cancel_pending_approval_cancels_both_run_and_request():
    engine, _, _, repo = make_engine(approval=True)
    run = engine.tick(start(engine).id)
    approval_id = run.approval_id
    run = engine.cancel(run.id)
    assert run.state.stage == "CANCELLED"
    assert repo.get(approval_id).status == "CANCELLED"
    with pytest.raises(InvalidTransition):
        engine.tick(run.id)


def test_approval_expiry_stops_run():
    engine, _, _, repo = make_engine(approval=True)
    engine._approval_policy = ApprovalPolicy(reviewers=["reviewer"], expires_in_seconds=1)
    run = engine.tick(start(engine).id)
    engine._clock = lambda: NOW + timedelta(seconds=2)
    run = engine.tick(run.id)
    assert run.state.stage == "FAILED"
    assert run.errors[0].code == "APPROVAL_EXPIRED"
    assert repo.get(run.approval_id).status == "EXPIRED"


def test_unknown_input_step_and_blank_identity_are_rejected():
    engine, _, _, _ = make_engine()
    with pytest.raises(ValueError):
        engine.start(task_id="task", project_id="project", inputs={"unknown": {}})
    with pytest.raises(ValueError):
        engine.start(task_id=" ", project_id="project")


def test_missing_approval_dependencies_rejected_at_construction():
    engine, _, _, _ = make_engine(approval=True)
    with pytest.raises(ValueError):
        Orchestrator(
            engine._definition,
            engine._registry,
            clock=lambda: NOW,
            new_id=lambda: "id",
        )


@pytest.mark.parametrize("defect", ["request-id", "agent-id", "waiting", "cancelled", "raises"])
def test_nonconforming_agent_result_does_not_dispatch_next_step(defect, monkeypatch):
    engine, spec, plan, _ = make_engine()
    execute = spec.execute

    def broken(request):
        if defect == "raises":
            raise RuntimeError("private plugin detail")
        result = execute(request)
        if defect == "request-id":
            return result.model_copy(update={"request_id": "wrong"})
        if defect == "agent-id":
            return result.model_copy(update={"agent_id": "wrong"})
        return result.model_copy(
            update={"status": "WAITING" if defect == "waiting" else "CANCELLED"},
        )

    monkeypatch.setattr(spec, "execute", broken)
    run = engine.tick(start(engine).id)
    assert run.state.stage == ("CANCELLED" if defect == "cancelled" else "FAILED")
    assert not plan.run_called
    assert run.artifacts == {}
    assert "private plugin detail" not in repr(run)


def test_missing_consumed_artifact_is_not_silently_ignored():
    engine, _, plan, _ = make_engine()
    run = engine.tick(start(engine).id)
    engine._runs[run.id].artifacts.clear()
    run = engine.tick(run.id)
    assert run.state.stage == "FAILED"
    assert run.errors[0].code == "VALIDATION_FAILED"
    assert not plan.run_called


def test_unavailable_agent_is_not_executed():
    engine, spec, _, _ = make_engine()
    spec._metadata = spec.metadata.model_copy(update={"status": "DISABLED"})
    run = engine.tick(start(engine).id)
    assert run.state.stage == "FAILED"
    assert not spec.run_called


def test_step_timeout_does_not_publish_artifacts():
    engine, spec, _, _ = make_engine()
    engine._definition.steps[0] = engine._definition.steps[0].model_copy(update={"timeout": 1})
    spec._runtime = AgentRuntime(
        models=ScriptedModelGateway([]),
        clock=iter([NOW, NOW + timedelta(seconds=2)]).__next__,
        new_id=lambda: "event",
    )
    run = engine.tick(start(engine).id)
    assert run.state.stage == "FAILED"
    assert run.errors[0].code == "WORKFLOW_STEP_TIMEOUT"
    assert run.artifacts == {}


def test_approval_repository_failure_does_not_leave_unrecoverable_review_stage(monkeypatch):
    engine, _, _, repo = make_engine(approval=True)

    def broken(approval):
        raise RuntimeError("private repository detail")

    monkeypatch.setattr(repo, "create", broken)
    run = engine.tick(start(engine).id)
    assert run.state.stage == "FAILED"
    assert run.approval_id is None
    assert run.artifacts == {}
    assert run.errors[0].code == "INTEGRATION_UNAVAILABLE"
    assert "private repository detail" not in repr(run)


def test_recursive_dispatch_and_cancellation_are_rejected(monkeypatch):
    engine, spec, _, _ = make_engine()
    run = start(engine)
    original = spec._run_behavior

    def reentrant(request):
        with pytest.raises(ValueError):
            engine.tick(run.id)
        with pytest.raises(ValueError):
            engine.cancel(run.id)
        return original(request)

    spec._run_behavior = reentrant
    assert engine.tick(run.id).state.stage == "PLAN"


def test_configured_retry_policy_is_executed_without_extra_calls_on_success():
    engine, spec, plan, _ = make_engine()
    definition = engine._definition.model_copy(deep=True)
    definition.steps[0] = definition.steps[0].model_copy(
        update={"retry_policy": RetryPolicySettings(max_attempts=2)},
    )
    engine = Orchestrator(
        definition,
        engine._registry,
        clock=lambda: NOW,
        new_id=engine._new_id,
    )
    run = engine.tick(start(engine).id)
    assert run.state.stage == "PLAN"
    assert spec.run_called and not plan.run_called
    assert run.attempts["spec"] == 1
    assert run.retry_at is None


def test_run_ids_must_be_unique_and_clock_must_be_aware():
    engine, _, _, _ = make_engine()
    engine._new_id = lambda: "fixed-id"
    start(engine)
    with pytest.raises(ValueError, match="unique"):
        start(engine)
    engine._clock = lambda: NOW.replace(tzinfo=None)
    with pytest.raises(ValueError, match="timezone-aware"):
        start(engine)
