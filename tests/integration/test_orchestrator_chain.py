from datetime import UTC, datetime
from itertools import count
from pathlib import Path

from asf.agents.base import AgentRuntime
from asf.agents.plan.factory import build_plan_agent
from asf.agents.spec.factory import build_spec_agent
from asf.approval.models import ApprovalPolicy
from asf.approval.service import ApprovalService
from asf.configuration.platform import PlatformConfig
from asf.models.fake import ScriptedModelGateway
from asf.orchestrator import AgentRegistry, Orchestrator
from asf.storage.memory import InMemoryApprovalRepository
from asf.workflow.definition import WorkflowDefinition, WorkflowStepDef
from tests.integration.test_chain import make_plan_artifact, make_spec_artifact


def test_actual_spec_and_plan_agents_are_sequenced_through_approval():
    now = datetime(2026, 11, 2, tzinfo=UTC)
    ids = count(1)

    def new_id():
        return f"id-{next(ids)}"

    spec_gateway = ScriptedModelGateway([make_spec_artifact().content["text"]])
    plan_gateway = ScriptedModelGateway([])
    templates = Path(__file__).resolve().parents[2] / "templates"
    registry = AgentRegistry()
    registry.register(
        build_spec_agent(
            AgentRuntime(models=spec_gateway, clock=lambda: now, new_id=new_id),
            PlatformConfig(),
            templates,
        )
    )
    registry.register(
        build_plan_agent(
            AgentRuntime(models=plan_gateway, clock=lambda: now, new_id=new_id),
            PlatformConfig(),
            templates,
        )
    )
    definition = WorkflowDefinition(
        id="spec-plan",
        name="Spec and Plan",
        version="1",
        steps=[
            WorkflowStepDef(
                id="spec",
                name="Spec",
                type="AGENT",
                stage="SPEC",
                agent_type="spec",
                requires_approval=True,
                produces=["SPEC"],
            ),
            WorkflowStepDef(
                id="plan",
                name="Plan",
                type="AGENT",
                stage="PLAN",
                agent_type="plan",
                requires_approval=True,
                consumes=["SPEC"],
                produces=["PLAN"],
            ),
        ],
    )
    repo = InMemoryApprovalRepository()
    engine = Orchestrator(
        definition,
        registry,
        clock=lambda: now,
        new_id=new_id,
        approvals=ApprovalService(repo, id_factory=new_id),
        approval_policy=ApprovalPolicy(reviewers=["reviewer"]),
    )
    run = engine.start(
        task_id="task-1",
        project_id="project-1",
        inputs={"spec": {"requirement": "Implement a calculator"}},
    )
    run = engine.tick(run.id)
    assert run.state.stage == "SPEC_REVIEW"
    assert len(spec_gateway.requests) == 1
    assert plan_gateway.requests == []
    spec_artifact = run.artifacts["SPEC"]
    plan_reply = (
        make_plan_artifact()
        .content["text"]
        .replace(
            "ID: spec-1",
            f"ID: {spec_artifact.id}",
        )
    )
    plan_gateway = ScriptedModelGateway([plan_reply])
    registry.unregister("agent-plan")
    registry.register(
        build_plan_agent(
            AgentRuntime(models=plan_gateway, clock=lambda: now, new_id=new_id),
            PlatformConfig(),
            templates,
        )
    )
    run = engine.decide(run.id, reviewer="reviewer", decision="APPROVED")
    assert run.state.stage == "PLAN_DRAFT"
    run = engine.tick(run.id)
    assert run.state.stage == "PLAN_REVIEW"
    assert run.artifacts["PLAN"].metadata["specArtifactId"] == spec_artifact.id
    assert len(plan_gateway.requests) == 1
    assert len(repo.list_pending()) == 1
    run = engine.decide(run.id, reviewer="reviewer", decision="APPROVED")
    assert run.state.stage == "COMPLETED"
    assert run.errors == []
    assert len(run.results) == 2
    assert repo.list_pending() == []
