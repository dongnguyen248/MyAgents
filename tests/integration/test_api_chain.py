"""End-to-end dashboard API chain: run -> approve SPEC -> approve PLAN."""

from __future__ import annotations

from fastapi.testclient import TestClient

from asf.api.app import create_app
from tests.unit.test_api_service import build_service


def test_dashboard_api_full_chain():
    service, _metrics = build_service()
    client = TestClient(create_app(service))

    created = client.post(
        "/runs", json={"taskId": "task-1", "projectId": "proj-1",
                       "inputs": {"spec": {"requirement": "Build a calculator"}}},
    )
    assert created.status_code == 201
    run_id = created.json()["id"]
    # Auto-advance: creation already ran the spec step to its gate.
    assert created.json()["status"] == "WAITING_APPROVAL"

    def tick() -> dict:
        response = client.post(f"/runs/{run_id}/tick")
        assert response.status_code == 200
        return response.json()

    def pending_approval() -> dict:
        approvals = client.get("/approvals").json()
        assert len(approvals) == 1
        return approvals[0]

    workflow = tick()
    assert workflow["status"] == "WAITING_APPROVAL"
    spec_approval = pending_approval()
    assert spec_approval["type"] == "SPEC"
    assert client.get("/tasks/task-1").json()["status"] == "SPEC_REVIEW"

    decided = client.post(
        f"/approvals/{spec_approval['id']}/decision", json={"decision": "APPROVE"},
    )
    assert decided.json()["status"] == "APPROVED"

    workflow = tick()
    assert workflow["status"] == "WAITING_APPROVAL"
    plan_approval = pending_approval()
    assert plan_approval["type"] == "PLAN"
    assert client.get("/tasks/task-1").json()["status"] == "PLAN_REVIEW"
    states = {step["id"]: step["state"] for step in workflow["steps"]}
    assert states["spec_approval"] == "done"
    assert states["plan_approval"] == "active"

    decided = client.post(
        f"/approvals/{plan_approval['id']}/decision", json={"decision": "APPROVE"},
    )
    assert decided.json()["status"] == "APPROVED"

    workflow = client.get(f"/workflows/{run_id}").json()
    assert workflow["status"] == "COMPLETED"
    assert all(step["state"] == "done" for step in workflow["steps"])
    task = client.get("/tasks/task-1").json()
    assert task["status"] == "COMPLETED"
    assert task["durationSec"] is not None
    assert client.get("/approvals").json() == []
    assert client.get("/activity").json()
    assert client.get(
        "/activity", params={"taskId": "task-1"},
    ).json()
