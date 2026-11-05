"""MetricsService wired as both orchestrator ports in a real run."""

from datetime import UTC, datetime
from itertools import count
from pathlib import Path

from asf.agents.base import AgentRuntime
from asf.agents.spec.factory import build_spec_agent
from asf.approval.models import ApprovalPolicy
from asf.approval.service import ApprovalService
from asf.configuration.platform import PlatformConfig
from asf.evaluation import MetricsService
from asf.models.fake import ScriptedModelGateway
from asf.orchestrator import AgentRegistry, Orchestrator
from asf.storage.memory import InMemoryApprovalRepository
from asf.workflow.definition import WorkflowDefinition, WorkflowStepDef
from tests.integration.test_chain import make_spec_artifact


def test_metrics_service_collects_metrics_and_events_from_orchestrator_run():
    now = datetime(2026, 11, 2, tzinfo=UTC)
    ids = count(1)

    def new_id():
        return f"id-{next(ids)}"

    gateway = ScriptedModelGateway([make_spec_artifact().content["text"]])
    templates = Path(__file__).resolve().parents[2] / "templates"
    registry = AgentRegistry()
    registry.register(
        build_spec_agent(
            AgentRuntime(models=gateway, clock=lambda: now, new_id=new_id),
            PlatformConfig(),
            templates,
        )
    )
    definition = WorkflowDefinition(
        id="spec-only",
        name="Spec only",
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
        ],
    )
    service = MetricsService(clock=lambda: now)
    engine = Orchestrator(
        definition,
        registry,
        clock=lambda: now,
        new_id=new_id,
        approvals=ApprovalService(InMemoryApprovalRepository(), id_factory=new_id),
        approval_policy=ApprovalPolicy(reviewers=["reviewer"]),
        events=service,
        metrics=service,
    )
    run = engine.start(
        task_id="task-1",
        project_id="project-1",
        inputs={"spec": {"requirement": "Implement a calculator"}},
    )
    run = engine.tick(run.id)
    assert run.state.stage == "SPEC_REVIEW"
    assert len(run.results) == 1

    # Observations sit in the outbox until flush_observations() delivers them:
    # nothing has reached the metrics service yet.
    assert service.agent_metrics("agent-spec")["total"] == 0
    assert service.events() == []

    run = engine.flush_observations(run.id)
    metrics = service.agent_metrics("agent-spec")
    assert metrics["total"] == 1
    assert metrics["completed"] == 1
    assert metrics["successRate"] == 1.0
    assert service.all_agent_metrics()["agent-spec"]["total"] == 1
    assert service.project_outcomes("project-1") == {
        "running": 0,
        "completed": 1,
        "failed": 0,
        "successRate": 1.0,
    }

    events = service.events()
    event_types = [event.event_type for event in events]
    assert event_types[0] == "WORKFLOW_STARTED"
    assert "AGENT_STARTED" in event_types
    assert "ARTIFACT_CREATED" in event_types
    assert "AGENT_COMPLETED" in event_types
    assert all(event.project_id == "project-1" for event in events)
    assert all(event.task_id == "task-1" for event in events)

    # Delivery is marked per observation: a second flush must not duplicate.
    engine.flush_observations(run.id)
    assert service.agent_metrics("agent-spec")["total"] == 1
    assert len(service.events()) == len(events)
