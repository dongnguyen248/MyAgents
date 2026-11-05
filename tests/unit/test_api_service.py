"""FactoryService mapping tests over a real spec -> plan orchestrator run."""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from itertools import count
from pathlib import Path

import pytest

from asf.agents.base import AgentRuntime
from asf.agents.plan.factory import build_plan_agent
from asf.agents.spec.factory import build_spec_agent
from asf.api.hosting_tokens import HostingTokens
from asf.api.service import (
    FactoryService,
    ProjectConflictError,
    ProjectExistsError,
    ProjectNotFoundError,
)
from asf.approval.models import ApprovalPolicy
from asf.approval.service import ApprovalService
from asf.configuration.platform import PlatformConfig
from asf.configuration.project import ProjectProfile
from asf.contracts.models import ModelRequest, ModelResponse
from asf.models.fake import ScriptedModelGateway
from asf.orchestrator import AgentRegistry, Orchestrator
from asf.storage.memory import InMemoryApprovalRepository
from asf.storage.sqlite import SQLiteExecutionStore
from asf.workflow.definition import WorkflowDefinition, WorkflowStepDef
from tests.integration.test_chain import make_plan_artifact, make_spec_artifact

NOW = datetime(2026, 11, 3, 9, 0, tzinfo=timezone.utc)
TEMPLATES = Path(__file__).resolve().parents[2] / "templates"

PROJECTS = {
    "proj-1": {
        "id": "proj-1", "name": "Project One",
        "repository": {"provider": "gitlab"},
        "technology": {"backend": ["python"], "frontend": ["react"]},
    },
    "proj-2": ProjectProfile(
        id="proj-2", name="Project Two", repository={"provider": "github"},
        technology={"backend": ["java", "spring"]}, workflow="software-development",
    ),
}


class RoutingGateway:
    """One deterministic gateway whose replies route on the system prompt."""

    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        system = request.messages[0].content
        if "business analyst" in system:
            reply = make_spec_artifact().content["text"]
        elif "software architect" in system:
            linked = re.search(
                r"## Linked SPEC\nID: ([^\n]+)\nVersion: ([^\n]+)",
                request.messages[-1].content,
            )
            assert linked is not None
            reply = make_plan_artifact().content["text"].replace(
                "ID: spec-1", f"ID: {linked[1]}",
            ).replace("Version: 1", f"Version: {linked[2]}", 1)
        else:  # pragma: no cover - the test workflow only uses spec/plan
            raise AssertionError(f"Unexpected model request: {system[:80]}")
        return ScriptedModelGateway([reply]).complete(request)


class FakeMetrics:
    """Small fake implementing the evaluation protocol used by the service."""

    def __init__(self) -> None:
        self.decisions: list[dict] = []
        self._overview = {
            "daily": [], "human": {"approvalRate": 1.0}, "quality": {}, "agents": [],
        }

    def agent_metrics(self, agent_id: str) -> dict:
        return {
            "total": 3, "completed": 2, "running": 1, "failed": 0, "cancelled": 0,
            "success_rate": 0.5, "avg_duration_sec": 12.0, "avg_revisions": 1.0,
            "human_approval_rate": 1.0, "test_pass_rate": 1.0, "ci_pass_rate": 1.0,
        }

    def overview(self) -> dict:
        return self._overview

    def events(self) -> list:
        return []

    def project_outcomes(self, project_id: str) -> dict:
        return {}

    def record_approval_decision(self, **kwargs) -> None:
        self.decisions.append(kwargs)


def build_engine(store=None) -> Orchestrator:
    ids = count(1)

    def new_id() -> str:
        return f"id-{next(ids)}"

    gateway = RoutingGateway()
    runtime = AgentRuntime(models=gateway, clock=lambda: NOW, new_id=new_id)
    registry = AgentRegistry()
    registry.register(build_spec_agent(runtime, PlatformConfig(), TEMPLATES))
    registry.register(build_plan_agent(runtime, PlatformConfig(), TEMPLATES))
    definition = WorkflowDefinition(
        id="spec-plan", name="Spec and Plan", version="1", steps=[
            WorkflowStepDef(
                id="spec", name="Spec", type="AGENT", stage="SPEC",
                agent_type="spec", requires_approval=True, produces=["SPEC"],
            ),
            WorkflowStepDef(
                id="plan", name="Plan", type="AGENT", stage="PLAN",
                agent_type="plan", requires_approval=True,
                consumes=["SPEC"], produces=["PLAN"],
            ),
        ],
    )
    kwargs: dict = {}
    if store is not None:
        kwargs["store"] = store
    else:
        kwargs["approvals"] = ApprovalService(
            InMemoryApprovalRepository(), id_factory=new_id,
        )
    return Orchestrator(
        definition, registry, clock=lambda: NOW, new_id=new_id,
        approval_policy=ApprovalPolicy(reviewers=["dashboard"]), **kwargs,
    )


def build_service(store=None, hosting_tokens=None) -> tuple[FactoryService, FakeMetrics]:
    metrics = FakeMetrics()
    service = FactoryService(
        build_engine(store), projects=PROJECTS, metrics=metrics,
        store=store, clock=lambda: NOW, hosting_tokens=hosting_tokens,
    )
    return service, metrics


def start_at_spec_review(service: FactoryService) -> str:
    run = service.start_run(
        "task-1", "proj-1", inputs={"spec": {"requirement": "Build a calculator"}},
    )
    view = service.tick_run(run.id)
    assert view is not None and view["status"] == "WAITING_APPROVAL"
    return run.id


def test_agents_config_and_metrics_normalization():
    service, _ = build_service()
    agents = service.list_agents()
    assert {agent["id"] for agent in agents} == {"agent-spec", "agent-plan"}
    spec = service.get_agent("agent-spec")
    assert spec is not None
    assert spec["status"] == "IDLE"
    assert spec["metrics"]["successRate"] == 0.5  # snake_case normalized
    assert spec["metrics"]["avgDurationSec"] == 12.0
    assert service.get_agent("agent-nope") is None

    config = service.get_agent_config("agent-spec")
    assert config is not None
    assert config["agentId"] == "agent-spec"
    assert config["skills"] == ["write-spec", "revise-spec"]
    assert config["allowedProjectIds"] == ["proj-1", "proj-2"]
    assert config["timeoutSeconds"] == 1800
    assert config["retryPolicy"] == {
        "maxRetries": 0, "backoff": "none", "backoffSeconds": 0,
    }
    assert service.get_agent_config("agent-nope") is None
    assert service.get_agent_runs("agent-spec") == []


def test_run_task_workflow_and_approval_flow():
    service, metrics = build_service()
    run_id = start_at_spec_review(service)

    task = service.get_task("task-1")
    assert task is not None
    assert task["status"] == "SPEC_REVIEW"
    assert task["priority"] == "MEDIUM"  # contract NORMAL mapped to MEDIUM
    assert task["assignedAgentId"] == "agent-spec"
    assert [t["id"] for t in service.list_tasks({"projectId": "proj-1"})] == ["task-1"]
    assert service.list_tasks({"projectId": "proj-2"}) == []
    assert service.list_tasks({"status": "COMPLETED"}) == []

    workflow = service.get_workflow(run_id)
    assert workflow is not None
    assert workflow["status"] == "WAITING_APPROVAL"
    states = {step["id"]: step["state"] for step in workflow["steps"]}
    assert states == {
        "spec": "done", "spec_approval": "active",
        "plan": "pending", "plan_approval": "pending",
    }

    approvals = service.list_approvals()
    assert len(approvals) == 1
    approval = approvals[0]
    assert approval["type"] == "SPEC"
    assert approval["status"] == "PENDING"
    assert approval["artifact"] == "SPEC.md"
    assert approval["summary"].startswith("SPEC")
    assert approval["artifactContent"].startswith("# SPEC: Test Feature")
    assert "REQ-1: Implement add(a, b)" in approval["artifactContent"]
    assert approval["requestedByAgentId"] == "agent-spec"
    assert approval["requestedAt"] == NOW.isoformat()

    decided = service.decide_approval(approval["id"], decision="APPROVE")
    assert decided["status"] == "APPROVED"
    assert metrics.decisions[0]["agent_id"] == "agent-spec"  # agent id, matching AgentResult keys
    assert metrics.decisions[0]["decision"] == "APPROVED"
    # Auto-advance: approving the spec already ran the plan step, so the
    # PLAN approval is pending without anyone ticking the run.
    service.wait_for_drives()
    plan_approvals = service.list_approvals()
    assert len(plan_approvals) == 1 and plan_approvals[0]["type"] == "PLAN"

    runs = service.get_agent_runs("agent-spec")
    assert len(runs) == 1
    assert runs[0]["status"] == "Completed"
    assert runs[0]["taskId"] == "task-1"

    # A manual tick at an approval gate remains a harmless no-op.
    view = service.tick_run(run_id)
    assert view is not None and view["status"] == "WAITING_APPROVAL"

    commented = service.decide_approval(
        plan_approvals[0]["id"], decision="COMMENT", comment="Looks close",
    )
    assert commented["status"] == "PENDING"
    assert commented["comments"][0]["author"] == "dashboard"
    assert len(service.list_approvals()) == 1  # comment changed no state

    changed = service.decide_approval(
        plan_approvals[0]["id"], decision="REQUEST_CHANGES", comment="Add risks",
    )
    assert changed["status"] == "CHANGES_REQUESTED"
    assert changed["comments"][-1]["text"] == "Add risks"
    # Auto-advance also covers rework: the plan agent already redid the
    # plan with the feedback and the task is back at the plan review gate.
    service.wait_for_drives()
    assert service.get_task("task-1")["status"] == "PLAN_REVIEW"

    activity = service.list_activity()
    assert activity  # orchestrator + agent events were collected
    assert all(event["timestamp"] for event in activity)
    assert service.list_activity({"taskId": "task-1"})
    assert service.list_activity({"taskId": "other"}) == []
    assert service.list_activity({"limit": 1}) == activity[:1]

    projects = {p["id"]: p for p in service.list_projects()}
    assert projects["proj-1"]["repositoryProvider"] == "gitlab"
    assert projects["proj-1"]["technologies"] == ["python", "react"]
    assert projects["proj-2"]["technologies"] == ["java", "spring"]
    assert set(projects["proj-1"]["agentIds"]) == {"agent-spec", "agent-plan"}
    assert projects["proj-1"]["ci"] == "UNKNOWN"

    assert service.get_metrics_overview()["human"]["approvalRate"] == 1.0


def test_metrics_overview_defaults_without_metrics():
    service = FactoryService(
        build_engine(), projects=PROJECTS, clock=lambda: NOW,
    )
    overview = service.get_metrics_overview()
    assert overview["daily"] == [] and overview["agents"] == []
    assert overview["human"]["approvalRate"] == 0.0
    agent = service.get_agent("agent-spec")
    assert agent is not None and agent["metrics"]["total"] == 0


def test_store_discovered_runs_are_listed(tmp_path):
    store = SQLiteExecutionStore(tmp_path / "executions.sqlite")
    try:
        engine = build_engine(store)
        run = engine.start(
            task_id="task-9", project_id="proj-1",
            inputs={"spec": {"requirement": "Stored run"}},
        )
        engine.tick(run.id)
        service = FactoryService(
            engine, projects=PROJECTS, store=store, clock=lambda: NOW,
        )
        assert [t["id"] for t in service.list_tasks()] == ["task-9"]
        assert service.get_workflow(run.id)["status"] == "WAITING_APPROVAL"
        assert len(service.list_approvals()) == 1
    finally:
        store.close()


NEW_PROJECT = {
    "id": "proj-3", "name": "Project Three",
    "repository": {"provider": "github"},
    "technology": {"backend": ["go"], "frontend": ["vue"]},
    "workflow": "software-development",
    "enabledSkills": ["go", "testing"],
    "configuration": {"approval": {"channel": "teams"}},
}


def test_create_project_registers_dashboard_view():
    service, _metrics = build_service()
    view = service.create_project(NEW_PROJECT)
    assert view["id"] == "proj-3"
    assert view["name"] == "Project Three"
    assert view["repositoryProvider"] == "github"
    assert view["technologies"] == ["go", "vue"]
    assert view["metrics"]["running"] == 0
    assert "proj-3" in {p["id"] for p in service.list_projects()}


def test_create_project_rejects_duplicate_and_invalid_payloads():
    service, _metrics = build_service()
    service.create_project(NEW_PROJECT)
    with pytest.raises(ProjectExistsError):
        service.create_project(NEW_PROJECT)
    with pytest.raises(ProjectExistsError):
        service.create_project({**NEW_PROJECT, "id": "proj-1"})
    with pytest.raises(ValueError):
        service.create_project({**NEW_PROJECT, "id": "Bad Id!"})
    with pytest.raises(ValueError):
        service.create_project(
            {key: value for key, value in NEW_PROJECT.items() if key != "name"},
        )
    with pytest.raises(ValueError):
        service.create_project({**NEW_PROJECT, "id": "proj-4", "bogus": 1})


def test_create_project_hook_runs_before_registration():
    seen: list[ProjectProfile] = []
    service = FactoryService(
        build_engine(), projects=PROJECTS, clock=lambda: NOW,
        on_project_created=seen.append,
    )
    service.create_project(NEW_PROJECT)
    assert [profile.id for profile in seen] == ["proj-3"]

    def failing_hook(profile: ProjectProfile) -> None:
        raise ValueError("disk full")

    blocked = FactoryService(
        build_engine(), projects=PROJECTS, clock=lambda: NOW,
        on_project_created=failing_hook,
    )
    with pytest.raises(ValueError, match="disk full"):
        blocked.create_project(NEW_PROJECT)
    assert "proj-3" not in {p["id"] for p in blocked.list_projects()}


def test_update_project_merges_over_stored_profile():
    service, _metrics = build_service()
    service.create_project(NEW_PROJECT)
    updated = service.update_project("proj-3", {"name": "Project Three v2"})
    assert updated["name"] == "Project Three v2"
    assert updated["repositoryProvider"] == "github"  # kept from stored profile
    assert updated["technologies"] == ["go", "vue"]
    assert updated["workflow"] == "software-development"
    assert updated["approvalChannel"] == "teams"


def test_update_project_unknown_and_id_change():
    service, _metrics = build_service()
    with pytest.raises(ProjectNotFoundError):
        service.update_project("nope", NEW_PROJECT)
    with pytest.raises(ValueError):
        service.update_project("proj-1", {**NEW_PROJECT, "id": "proj-9"})


def test_project_hosting_token_lifecycle():
    tokens = HostingTokens()
    service, _metrics = build_service(hosting_tokens=tokens)

    # Create with a token: stored apart from the profile, view shows
    # only configured + last-4 hint, token appears nowhere else.
    view = service.create_project(
        {**NEW_PROJECT, "hostingToken": "glpat-secret-1234"},
    )
    assert view["hostingTokenConfigured"] is True
    assert view["hostingTokenHint"] == "…1234"
    assert "glpat-secret-1234" not in json.dumps(view)
    assert "glpat-secret-1234" not in json.dumps(
        service._project_profiles["proj-3"],
    )
    assert tokens.get("proj-3") == "glpat-secret-1234"

    # An update without a token keeps the stored one.
    view = service.update_project("proj-3", {"name": "Project Three"})
    assert view["hostingTokenHint"] == "…1234"

    # A new token replaces it.
    view = service.update_project(
        "proj-3", {"hostingToken": "glpat-other-9876"},
    )
    assert view["hostingTokenHint"] == "…9876"
    assert tokens.get("proj-3") == "glpat-other-9876"

    # The clear flag removes it (no URL on this project, so the env
    # fallback reports not-configured).
    view = service.update_project("proj-3", {"clearHostingToken": True})
    assert view["hostingTokenConfigured"] is False
    assert view["hostingTokenHint"] is None
    assert tokens.get("proj-3") is None

    # Deleting the project removes any stored token too.
    service.update_project("proj-3", {"hostingToken": "glpat-secret-1234"})
    service.delete_project("proj-3")
    assert tokens.get("proj-3") is None


def test_project_hosting_token_requires_a_store():
    service, _metrics = build_service()
    with pytest.raises(ValueError, match="no hosting-token store"):
        service.create_project(
            {**NEW_PROJECT, "hostingToken": "glpat-secret-1234"},
        )


def test_delete_project_rules():
    service, _metrics = build_service()
    service.create_project(NEW_PROJECT)
    service.delete_project("proj-3")
    assert "proj-3" not in {p["id"] for p in service.list_projects()}
    with pytest.raises(ProjectNotFoundError):
        service.delete_project("proj-3")


def test_delete_project_blocked_while_run_active():
    service, _metrics = build_service()
    start_at_spec_review(service)  # proj-1 run waiting at SPEC_REVIEW
    with pytest.raises(ProjectConflictError):
        service.delete_project("proj-1")


def test_project_view_exposes_repository_url():
    service, _metrics = build_service()
    created = service.create_project({
        **NEW_PROJECT,
        "repository": {
            "provider": "gitlab",
            "url": "https://gitlab.com/group/proj-3",
        },
    })
    assert created["repositoryUrl"] == "https://gitlab.com/group/proj-3"
    listed = next(p for p in service.list_projects() if p["id"] == "proj-1")
    assert listed["repositoryUrl"] == ""


def test_project_view_exposes_workspace_fields():
    service, _metrics = build_service()
    created = service.create_project({
        **NEW_PROJECT,
        "repository": {"provider": "github", "path": "/srv/proj-3"},
        "configuration": {
            "testCommands": [["python", "-m", "pytest", "-q"]],
        },
    })
    assert created["repositoryPath"] == "/srv/proj-3"
    assert created["testCommands"] == [["python", "-m", "pytest", "-q"]]
    updated = service.update_project("proj-3", {"repository": {"path": ""}})
    assert updated["repositoryPath"] == ""
    assert updated["repositoryProvider"] == "github"  # merge kept it
    listed = next(p for p in service.list_projects() if p["id"] == "proj-1")
    assert listed["repositoryPath"] == ""
    assert listed["testCommands"] == []


def test_update_and_delete_hooks_run_in_order():
    calls: list = []
    service = FactoryService(
        build_engine(), projects=PROJECTS, clock=lambda: NOW,
        on_project_updated=lambda profile: calls.append(("updated", profile.id)),
        on_project_deleted=lambda pid: calls.append(("deleted", pid)),
    )
    service.create_project(NEW_PROJECT)
    service.update_project("proj-3", {"name": "Renamed"})
    service.delete_project("proj-3")
    assert calls == [("updated", "proj-3"), ("deleted", "proj-3")]
def test_artifact_text_renders_structured_content_as_json():
    class FakeArtifact:
        content = {"changes": [{"path": "a.py", "operation": "create"}]}

    rendered = FactoryService._artifact_text(FakeArtifact())
    assert rendered is not None
    assert '"path": "a.py"' in rendered
    assert FactoryService._artifact_text(None) is None


def test_cancel_run_at_approval_gate_cancels_immediately():
    engine = build_engine()
    service = FactoryService(
        engine, projects=PROJECTS, metrics=FakeMetrics(), clock=lambda: NOW,
    )
    run_id = start_at_spec_review(service)
    assert len(service.list_approvals()) == 1

    view = service.cancel_run(run_id)

    assert view is not None and view["status"] == "CANCELLED"
    assert engine.get(run_id).state.stage == "CANCELLED"
    # The pending approval is cancelled with the run, not left decidable.
    assert service.list_approvals() == []
    with pytest.raises(ValueError, match="already cancelled"):
        service.cancel_run(run_id)
    with pytest.raises(KeyError):
        service.cancel_run("run-missing")


def test_cancel_run_while_driving_is_applied_between_steps():
    engine = build_engine()
    service = FactoryService(
        engine, projects=PROJECTS, metrics=FakeMetrics(), clock=lambda: NOW,
    )
    run = engine.start(
        task_id="task-1", project_id="proj-1",
        inputs={"spec": {"requirement": "Build a calculator"}},
    )
    service.track(run.id)
    # Pretend a background drive is mid-dispatch for this run: the
    # engine cannot be mutated safely right now, so the service must
    # record the request instead of cancelling synchronously.
    service._drive_threads[run.id] = threading.Thread()
    try:
        view = service.cancel_run(run.id)
        assert view is not None and view["status"] != "CANCELLED"
        assert engine.get(run.id).state.stage != "CANCELLED"
        assert run.id in service._cancel_requested

        # The drive applies the recorded request before its next step.
        service._drive(run.id)
        assert engine.get(run.id).state.stage == "CANCELLED"
        assert run.id not in service._cancel_requested
    finally:
        service._drive_threads.pop(run.id, None)


def test_run_log_records_step_started_before_its_result():
    engine = build_engine()
    service = FactoryService(
        engine, projects=PROJECTS, metrics=FakeMetrics(), clock=lambda: NOW,
    )
    run = service.start_run(
        "task-1", "proj-1", inputs={"spec": {"requirement": "Build a calculator"}},
    )
    service.wait_for_drives(timeout=10)

    observations = engine.get(run.id).observations
    started = [
        o.event for o in observations
        if o.event is not None and o.event.event_type == "STEP_STARTED"
    ]
    assert len(started) == 1
    assert started[0].message == "Spec started"
    assert started[0].metadata["stepId"] == "spec"
    # The start line precedes the step's result in the run's log.
    kinds = [
        o.event.event_type if o.event is not None else "RESULT"
        for o in observations
    ]
    assert kinds.index("STEP_STARTED") < kinds.index("RESULT")
    # ...and it reaches the dashboard activity feed.
    activity = service.list_activity({"taskId": "task-1"})
    assert any(a["message"] == "Spec started" for a in activity)
    # Parked at the approval gate, the run reports no live activity.
    view = service.get_workflow(run.id)
    assert view is not None and view["currentActivity"] is None


def test_workflow_view_reports_current_activity_while_in_flight():
    engine = build_engine()
    service = FactoryService(
        engine, projects=PROJECTS, metrics=FakeMetrics(), clock=lambda: NOW,
    )
    run = engine.start(
        task_id="task-1", project_id="proj-1",
        inputs={"spec": {"requirement": "Build a calculator"}},
    )
    service.track(run.id)
    # Stamp the in-flight marker exactly as tick does before dispatching.
    engine._runs[run.id].in_flight = "dispatch-1"

    view = service.get_workflow(run.id)

    assert view is not None
    activity = view["currentActivity"]
    assert activity["kind"] == "STEP_RUNNING"
    assert activity["stepId"] == "spec"
    assert activity["stepLabel"] == "Spec"
    assert activity["since"] == NOW.isoformat()
