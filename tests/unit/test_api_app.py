"""FastAPI adapter tests: routes, status codes, and the decision flow."""

from __future__ import annotations

from fastapi.testclient import TestClient

from asf.api.app import create_app
from tests.unit.test_api_service import build_service


def make_client() -> TestClient:
    service, _metrics = build_service()
    return TestClient(create_app(service))


def test_health_agents_and_404s():
    client = make_client()
    assert client.get("/health").json() == {"status": "ok"}

    agents = client.get("/agents")
    assert agents.status_code == 200
    assert {agent["id"] for agent in agents.json()} == {"agent-spec", "agent-plan"}

    assert client.get("/agents/agent-spec").status_code == 200
    assert client.get("/agents/agent-nope").status_code == 404
    config = client.get("/agents/agent-spec/config")
    assert config.status_code == 200
    assert config.json()["agentId"] == "agent-spec"
    assert client.get("/agents/agent-nope/config").status_code == 404
    assert client.get("/agents/agent-spec/runs").json() == []

    assert client.get("/tasks/nope").status_code == 404
    assert client.get("/workflows/nope").status_code == 404
    assert client.get("/projects").status_code == 200
    overview = client.get("/metrics/overview")
    assert overview.status_code == 200
    assert overview.json()["human"]["approvalRate"] == 1.0


def test_run_approval_decision_flow_over_http():
    client = make_client()
    created = client.post(
        "/runs", json={"taskId": "task-1", "projectId": "proj-1",
                       "inputs": {"spec": {"requirement": "Build a calculator"}}},
    )
    assert created.status_code == 201
    run_id = created.json()["id"]

    ticked = client.post(f"/runs/{run_id}/tick")
    assert ticked.status_code == 200
    assert ticked.json()["status"] == "WAITING_APPROVAL"

    approvals = client.get("/approvals")
    assert approvals.status_code == 200
    assert len(approvals.json()) == 1
    approval_id = approvals.json()[0]["id"]

    decided = client.post(
        f"/approvals/{approval_id}/decision", json={"decision": "APPROVE"},
    )
    assert decided.status_code == 200
    assert decided.json()["status"] == "APPROVED"

    conflict = client.post(
        "/approvals/approval-missing/decision", json={"decision": "APPROVE"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "NOT_FOUND"

    tasks = client.get("/tasks", params={"projectId": "proj-1"})
    assert [task["id"] for task in tasks.json()] == ["task-1"]
    assert client.get("/tasks/task-1").json()["status"] == "PLAN_DRAFT"
    assert client.get(f"/workflows/{run_id}").json()["id"] == run_id
    assert client.get("/activity").json()

    missing_tick = client.post("/runs/run-missing/tick")
    assert missing_tick.status_code == 404


def test_create_project_over_http():
    client = make_client()
    payload = {
        "id": "proj-3", "name": "Project Three",
        "repository": {"provider": "github"},
        "technology": {"backend": ["go"], "frontend": []},
        "workflow": "software-development",
        "enabledSkills": ["go"],
        "configuration": {"approval": {"channel": "teams"}},
    }
    created = client.post("/projects", json=payload)
    assert created.status_code == 201
    assert created.json()["id"] == "proj-3"
    assert created.json()["technologies"] == ["go"]
    assert "proj-3" in {p["id"] for p in client.get("/projects").json()}

    assert client.post("/projects", json=payload).status_code == 409
    invalid = {key: value for key, value in payload.items() if key != "name"}
    invalid["id"] = "proj-4"
    assert client.post("/projects", json=invalid).status_code == 422


def test_update_and_delete_project_over_http():
    client = make_client()
    payload = {
        "id": "proj-3", "name": "Project Three",
        "repository": {"provider": "github"},
        "technology": {"backend": ["go"], "frontend": []},
        "workflow": "software-development",
        "enabledSkills": ["go"],
        "configuration": {"approval": {"channel": "teams"}},
    }
    assert client.post("/projects", json=payload).status_code == 201
    updated = client.put(
        "/projects/proj-3", json={**payload, "name": "Project Three v2"},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Project Three v2"
    assert client.put("/projects/nope", json=payload).status_code == 404
    assert client.put(
        "/projects/proj-3", json={**payload, "id": "proj-9"},
    ).status_code == 422
    assert client.delete("/projects/proj-3").status_code == 204
    assert client.delete("/projects/proj-3").status_code == 404


def test_delete_project_with_active_run_conflicts_over_http():
    client = make_client()
    created = client.post(
        "/runs", json={"taskId": "task-1", "projectId": "proj-1",
                       "inputs": {"spec": {"requirement": "Build a calculator"}}},
    )
    run_id = created.json()["id"]
    client.post(f"/runs/{run_id}/tick")
    assert client.delete("/projects/proj-1").status_code == 409


def test_resume_endpoint_rejects_non_failed_runs():
    client = make_client()
    created = client.post(
        "/runs", json={"taskId": "task-1", "projectId": "proj-1",
                       "inputs": {"spec": {"requirement": "Build a calculator"}}},
    )
    assert created.status_code == 201
    run_id = created.json()["id"]

    active = client.post(f"/runs/{run_id}/resume")
    assert active.status_code == 409
    assert "has not failed" in active.json()["detail"]
    assert client.post("/runs/run-missing/resume").status_code == 404

    assert client.post(f"/runs/{run_id}/cancel").status_code == 200
    assert client.post(f"/runs/{run_id}/resume").status_code == 409
