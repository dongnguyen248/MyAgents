"""Stage 4B: the run-scoped test skip and the decision audit list.

A docs-only multi-item run used to stop at TEST_ESCALATED once per
item. An operator may now record ONE run-scoped skip (mandatory
reason, explicit scope) at the first stop; the engine applies that
recorded decision to later items whose pytest collects nothing —
each application still appends its own decision entry, audit note
and TESTS_SKIPPED event. Items with real tests are untouched.
"""

from __future__ import annotations

import json

import pytest

from asf.orchestrator.code_loop import TEST_ESCALATED_STAGE
from asf.orchestrator.test_ops import (
    SkipRequest,
    TestCommandReplacement,
    replace_test_commands,
    skip_tests,
)
from tests.integration.test_chain import make_task_artifact
from tests.integration.test_orchestrator_rework import change, harness, review

REASON = "docs-only project; the suite lives elsewhere"
_STOPS = ("COMPLETED", "FAILED", "CODE_FIX_ESCALATED", "TEST_ESCALATED")


def _drive(engine, run, *, limit=60):
    for _ in range(limit):
        if run.state.stage in _STOPS:
            return run
        if run.approval_id:
            run = engine.decide(run.id, reviewer="reviewer", decision="APPROVED")
        else:
            run = engine.tick(run.id)
    pytest.fail("Orchestrator did not reach a bounded stop")


def _task_reply(count: int) -> str:
    first = json.loads(make_task_artifact().content["text"])["tasks"][0]
    tasks = []
    for index in range(1, count + 1):
        path = "calculator.py" if index == 1 else f"part{index}.py"
        tasks.append(
            {
                **first,
                "id": f"T{index}",
                "title": f"Part {index}",
                "dependsOn": [] if index == 1 else [f"T{index - 1}"],
                "expectedFiles": [path],
            }
        )
    return json.dumps({"tasks": tasks})


def _implement_replies(count: int) -> list[str]:
    return [
        change() if index == 1 else change(f"part{index}.py", f"def part{index}(): return {index}")
        for index in range(1, count + 1)
    ]


def _events(run, event_type: str) -> list:
    return [
        obs.event
        for obs in run.observations
        if obs.event is not None and obs.event.event_type == event_type
    ]


def test_run_scoped_skip_covers_three_items_with_a_full_trail(tmp_path):
    engine, run, store, gateways, _repo, sandbox = harness(
        tmp_path,
        task_reply=_task_reply(3),
        review_replies=[review(), review(), review()],
        exits=[5, 5, 5],
        implement_replies=_implement_replies(3),
    )
    run = _drive(engine, run)
    assert run.state.stage == TEST_ESCALATED_STAGE
    run = skip_tests(engine, SkipRequest(run.id, REASON, "dong", scope="run"))
    run = _drive(engine, run)
    assert run.state.stage == "COMPLETED"
    assert run.errors == []
    assert gateways["fix"].requests == []
    assert len(sandbox.calls) == 3
    standing = run.context["testSkipRemaining"]
    assert standing["reason"] == REASON
    assert standing["operator"] == "dong"
    assert standing["itemId"] == "T1"
    decisions = run.context["testDecisions"]
    assert [entry["itemId"] for entry in decisions] == ["T1", "T2", "T3"]
    assert [entry["via"] for entry in decisions] == ["operator", "run-scope", "run-scope"]
    assert run.context["testDecision"] == decisions[-1]
    skipped = _events(run, "TESTS_SKIPPED")
    assert len(skipped) == 3
    assert skipped[0].metadata["operator"] == "dong"
    assert skipped[0].metadata["scope"] == "run"
    assert "via" not in skipped[0].metadata
    assert skipped[1].metadata["via"] == "run-scope"
    assert skipped[2].metadata["via"] == "run-scope"
    assert len(_events(run, "WORKFLOW_ESCALATED")) == 1
    store.close()


def test_run_scoped_skip_leaves_an_item_with_real_tests_alone(tmp_path):
    engine, run, store, _gateways, _repo, sandbox = harness(
        tmp_path,
        task_reply=_task_reply(2),
        review_replies=[review(), review()],
        exits=[5, 0],
        implement_replies=_implement_replies(2),
    )
    run = _drive(engine, run)
    assert run.state.stage == TEST_ESCALATED_STAGE
    run = skip_tests(engine, SkipRequest(run.id, REASON, "dong", scope="run"))
    run = _drive(engine, run)
    assert run.state.stage == "COMPLETED"
    assert len(sandbox.calls) == 2
    report = run.item_results["T2"]["TEST_REPORT"]
    assert report.content["report"]["verdict"] == "PASS"
    assert len(run.context["testDecisions"]) == 1
    assert run.context["testSkipRemaining"]["reason"] == REASON
    assert len(_events(run, "WORKFLOW_ESCALATED")) == 1
    store.close()


def test_item_scoped_skip_records_no_standing_decision(tmp_path):
    engine, run, store, _gateways, _repo, _sandbox = harness(
        tmp_path,
        review_replies=[review()],
        exits=[5],
    )
    run = _drive(engine, run)
    assert run.state.stage == TEST_ESCALATED_STAGE
    run = skip_tests(engine, SkipRequest(run.id, REASON, "dong"))
    run = _drive(engine, run)
    assert run.state.stage == "COMPLETED"
    assert "testSkipRemaining" not in run.context
    decisions = run.context["testDecisions"]
    assert len(decisions) == 1
    assert decisions[0]["via"] == "operator"
    assert decisions[0]["itemId"] == "T1"
    skipped = _events(run, "TESTS_SKIPPED")
    assert skipped[0].metadata["operator"] == "dong"
    assert "via" not in skipped[0].metadata
    assert "scope" not in skipped[0].metadata
    store.close()


def test_replace_clears_a_recorded_run_scoped_skip(tmp_path):
    engine, run, store, _gateways, _repo, _sandbox = harness(
        tmp_path,
        review_replies=[review()],
        exits=[5, 0],
    )
    run = _drive(engine, run)
    assert run.state.stage == TEST_ESCALATED_STAGE
    with engine._edit(run.id) as stored:
        stored.context["testSkipRemaining"] = {
            "reason": REASON,
            "operator": "dong",
            "at": "2026-11-09T00:00:00+00:00",
            "itemId": "T1",
        }
    run = replace_test_commands(
        engine,
        TestCommandReplacement(run_id=run.id, commands=[["pytest", "-q"]], operator="dong"),
    )
    assert "testSkipRemaining" not in run.context
    replaced = _events(run, "TEST_COMMANDS_REPLACED")
    assert replaced[0].metadata["clearedRunScopeSkip"] is True
    assert any("run-scoped test skip was cleared" in note for note in run.recovery_notes)
    run = _drive(engine, run)
    assert run.state.stage == "COMPLETED"
    store.close()


def test_resume_fork_inherits_the_run_scoped_skip(tmp_path):
    engine, run, store, _gateways, _repo, _sandbox = harness(
        tmp_path,
        task_reply=_task_reply(2),
        review_replies=[review(), review()],
        exits=[5],
        implement_replies=_implement_replies(2),
    )
    run = _drive(engine, run)
    assert run.state.stage == TEST_ESCALATED_STAGE
    run = skip_tests(engine, SkipRequest(run.id, REASON, "dong", scope="run"))
    assert run.state.stage != TEST_ESCALATED_STAGE
    engine.fail_run(run.id, reason="operator gives up for now", operator="dong")
    fork = engine.resume_failed(run.id)
    assert fork.context["testSkipRemaining"]["reason"] == REASON
    assert fork.context["testSkipRemaining"]["itemId"] == "T1"
    assert len(fork.context["testDecisions"]) == 1
    store.close()
