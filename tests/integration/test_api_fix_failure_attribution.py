"""Failed-step attribution for runs that die inside the code-fix loop.

Every quality artifact is published before the Fix agent runs, so a
naive "first step whose outputs are missing" rule blames the CI step.
The view must instead blame the step whose verdict triggered the fix,
and carry the fix validation details that explain the rejection. The
same history trap applies to a crash on a later cycle (a re-review or
re-test after a successful fix): the step the run died in, taken from
its event trail, is the failed step.
"""

from __future__ import annotations

import pytest

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
        tmp_path,
        review_replies=[review(), review()],
        exits=[1, 0],
        fix_replies=[change("outside.py")],
        with_actions=True,
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
    assert view["error"]["stage"] == "CODE_FIX"
    store.close()


def test_fix_rejected_after_review_changes_blames_code_review(tmp_path):
    engine, run, store, _, _, _ = harness(
        tmp_path,
        review_replies=[review("CHANGES_REQUESTED"), review()],
        exits=[0],
        fix_replies=[change("outside.py")],
        with_actions=True,
    )
    run = drive(engine, run)
    assert run.state.stage == "FAILED"
    view = _view(engine, run.id)
    states = {step["id"]: step["state"] for step in view["steps"]}
    assert states["code_review"] == "failed"
    assert states["testing"] == "pending"
    assert states["ci"] == "pending"
    store.close()


def test_crash_on_second_review_blames_code_review(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Cycle 1: tests fail, the fix lands. Cycle 2: the review agent
    itself dies (e.g. the model provider times out). Every artifact
    exists in the history, but the run died in Review code — not CI."""
    engine, run, store, _, _, _ = harness(
        tmp_path,
        review_replies=[review(), review()],
        exits=[1, 0],
        fix_replies=[change()],
        with_actions=True,
    )
    review_agent = engine._registry.for_type("review")
    original = review_agent.execute
    calls = {"count": 0}

    def flaky(request: object) -> object:
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("provider timed out")
        return original(request)

    monkeypatch.setattr(review_agent, "execute", flaky)
    run = drive(engine, run)
    assert run.state.stage == "FAILED"
    view = _view(engine, run.id)
    states = {step["id"]: step["state"] for step in view["steps"]}
    assert states["code_review"] == "failed"
    assert states["testing"] == "done"
    assert states["ci"] == "pending"
    assert view["error"]["stage"] == "CODE_REVIEW"
    store.close()
