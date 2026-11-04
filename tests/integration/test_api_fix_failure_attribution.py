"""Failed-step attribution for runs that die inside the code-fix loop.

Every quality artifact is published before the Fix agent runs, so a
naive "first step whose outputs are missing" rule blames the CI step.
The view must instead blame the step whose verdict triggered the fix,
and carry the fix validation details that explain the rejection.
"""
from __future__ import annotations

from asf.api.service import FactoryService
from tests.integration.test_orchestrator_rework import change, drive, harness, review


def _view(engine, run_id: str) -> dict:
    service = FactoryService(engine, projects={"project-1": {"name": "Project One"}})
    service.track(run_id)
    view = service.get_workflow(run_id)
    assert view is not None
    return view


def test_fix_rejected_after_test_failure_blames_run_tests(tmp_path):
    engine, run, store, _, _, _ = harness(
        tmp_path, review_replies=[review(), review()], exits=[1, 0],
        fix_replies=[change("outside.py")], with_actions=True,
    )
    run = drive(engine, run)
    assert run.state.stage == "FAILED"
    assert run.errors[-1].code == "LLM_INVALID_RESPONSE"
    view = _view(engine, run.id)
    assert view["status"] == "FAILED"
    states = {step["id"]: step["state"] for step in view["steps"]}
    assert states["testing"] == "failed"
    assert states["ci"] == "pending"
    assert states["merge"] == "pending"
    assert view["error"]["details"]["outOfScopePaths"] == ["outside.py"]
    store.close()


def test_fix_rejected_after_review_changes_blames_code_review(tmp_path):
    engine, run, store, _, _, _ = harness(
        tmp_path, review_replies=[review("CHANGES_REQUESTED"), review()],
        exits=[0], fix_replies=[change("outside.py")], with_actions=True,
    )
    run = drive(engine, run)
    assert run.state.stage == "FAILED"
    view = _view(engine, run.id)
    states = {step["id"]: step["state"] for step in view["steps"]}
    assert states["code_review"] == "failed"
    assert states["testing"] == "pending"
    assert states["ci"] == "pending"
    store.close()
