"""Item 5 HTTP surface: the two TEST_ESCALATED operator decisions.

Runs are parked at TEST_ESCALATED by direct state injection (the
operator-controls idiom); the engine-level behaviour is covered by
tests/integration/test_no_tests_operator.py.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from asf.api.app import create_app
from asf.api.demo import build_demo
from asf.orchestrator.code_loop import TEST_ESCALATED_STAGE
from asf.state_machine.machine import RunState

REASON = "Docs-only change; the real suite lives elsewhere"


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    service, engine, store = build_demo(tmp_path_factory.mktemp("no-tests"), ephemeral=True)
    return service, engine, store


@pytest.fixture(scope="module")
def client(demo):
    service, _engine, _store = demo
    return TestClient(create_app(service))


def _parked_run(service, engine) -> str:
    run = service.start_run(
        "task-no-tests",
        "vhpc",
        inputs={"spec": {"requirement": "Write the docs"}},
        context={"approval": {"overrides": {"mode": "human"}}},
    )
    service.wait_for_drives(timeout=10)
    with engine._edit(run.id) as stored:
        stored.state = RunState(stage=TEST_ESCALATED_STAGE, revisions={})
        stored.approval_id = None
    return run.id


def test_skip_tests_requires_a_reason(client, demo):
    service, engine, _store = demo
    run_id = _parked_run(service, engine)
    assert client.post(f"/runs/{run_id}/escalation/skip-tests", json={}).status_code == 422
    assert (
        client.post(f"/runs/{run_id}/escalation/skip-tests", json={"reason": "   "}).status_code
        == 422
    )


def test_skip_tests_records_the_decision(client, demo):
    service, engine, _store = demo
    run_id = _parked_run(service, engine)
    response = client.post(
        f"/runs/{run_id}/escalation/skip-tests",
        json={"reason": REASON},
        headers={"X-Operator": "dong"},
    )
    assert response.status_code == 200
    service.wait_for_drives(timeout=10)
    decision = engine.get(run_id).context["testDecision"]
    assert decision["action"] == "skip"
    assert decision["reason"] == REASON
    assert decision["operator"] == "dong"


def test_replace_test_commands_validates_before_storing(client, demo):
    service, engine, _store = demo
    run_id = _parked_run(service, engine)
    bad = client.post(
        f"/runs/{run_id}/escalation/test-commands",
        json={"commands": [[r"C:\tools\pytest.exe", "-q"]]},
    )
    assert bad.status_code == 422
    assert "testDecision" not in engine.get(run_id).context
    good = client.post(
        f"/runs/{run_id}/escalation/test-commands",
        json={"commands": [["python", "-m", "pytest", "-q"]]},
        headers={"X-Operator": "dong"},
    )
    assert good.status_code == 200
    service.wait_for_drives(timeout=10)
    run = engine.get(run_id)
    assert run.context["project"]["testCommands"] == [["python", "-m", "pytest", "-q"]]
    assert run.context["testDecision"]["action"] == "replace"


def test_decisions_are_conflicts_away_from_the_test_stop(client, demo):
    service, engine, _store = demo
    run = service.start_run(
        "task-no-tests-other",
        "vhpc",
        inputs={"spec": {"requirement": "Write the docs"}},
        context={"approval": {"overrides": {"mode": "human"}}},
    )
    service.wait_for_drives(timeout=10)
    assert engine.get(run.id).state.stage != TEST_ESCALATED_STAGE
    skip = client.post(f"/runs/{run.id}/escalation/skip-tests", json={"reason": REASON})
    assert skip.status_code == 409
    replace = client.post(
        f"/runs/{run.id}/escalation/test-commands",
        json={"commands": [["pytest", "-q"]]},
    )
    assert replace.status_code == 409


def test_decisions_on_a_missing_run_are_404(client):
    assert (
        client.post("/runs/nope/escalation/skip-tests", json={"reason": REASON}).status_code == 404
    )
    assert (
        client.post(
            "/runs/nope/escalation/test-commands",
            json={"commands": [["pytest", "-q"]]},
        ).status_code
        == 404
    )


def test_skip_tests_run_scope_records_the_standing_decision(client, demo):
    service, engine, _store = demo
    run_id = _parked_run(service, engine)
    response = client.post(
        f"/runs/{run_id}/escalation/skip-tests",
        json={"reason": REASON, "scope": "run"},
        headers={"X-Operator": "dong"},
    )
    assert response.status_code == 200
    service.wait_for_drives(timeout=10)
    context = engine.get(run_id).context
    standing = context["testSkipRemaining"]
    assert standing["reason"] == REASON
    assert standing["operator"] == "dong"
    assert context["testDecisions"][0]["action"] == "skip"


def test_skip_tests_rejects_an_unknown_scope(client, demo):
    service, engine, _store = demo
    run_id = _parked_run(service, engine)
    response = client.post(
        f"/runs/{run_id}/escalation/skip-tests",
        json={"reason": REASON, "scope": "project"},
    )
    assert response.status_code == 422
    assert "testSkipRemaining" not in engine.get(run_id).context


def test_skip_tests_run_scope_still_requires_a_reason(client, demo):
    service, engine, _store = demo
    run_id = _parked_run(service, engine)
    response = client.post(f"/runs/{run_id}/escalation/skip-tests", json={"scope": "run"})
    assert response.status_code == 422
