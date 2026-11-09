"""Item 5 operator decisions at TEST_ESCALATED: skip and replace.

Drives the rework harness to the NO_TESTS stop (real Test agent,
sandbox exit 5), then exercises the engine-level operator actions
in ``asf.orchestrator.test_ops``.
"""

from __future__ import annotations

import json

import pytest

from asf.orchestrator.code_loop import TEST_ESCALATED_STAGE
from asf.orchestrator.test_ops import (
    TestCommandReplacement,
    replace_test_commands,
    skip_tests,
)
from tests.integration.test_no_tests_routing import _drive
from tests.integration.test_orchestrator_rework import change, harness, review

REASON = "Docs-only change; the real suite lives in the .NET repo"


def _two_item_task() -> str:
    task = {
        "title": "Item",
        "milestoneRef": "M1",
        "description": "Do the item",
        "acceptanceCriteria": ["It works"],
        "dependsOn": [],
        "verificationHint": "Run unit tests",
    }
    return json.dumps(
        {
            "tasks": [
                {**task, "id": "T1", "expectedFiles": ["calculator.py"]},
                {**task, "id": "T2", "expectedFiles": ["extra.py"]},
            ]
        }
    )


def _escalated(tmp_path, **kwargs):
    engine, run, store, gateways, _repo, sandbox = harness(
        tmp_path, review_replies=[review()], exits=[5], **kwargs
    )
    run = _drive(engine, run)
    assert run.state.stage == TEST_ESCALATED_STAGE
    return engine, run, store, gateways, sandbox


def _events(run, event_type: str) -> list:
    return [
        obs.event
        for obs in run.observations
        if obs.event is not None and obs.event.event_type == event_type
    ]


def test_skip_on_the_last_item_completes_the_run(tmp_path):
    engine, run, store, _gateways, _sandbox = _escalated(tmp_path)
    report_id = run.artifacts["TEST_REPORT"].id
    run = skip_tests(engine, run.id, reason=REASON, operator="dong")
    assert run.state.stage == "COMPLETED"
    decision = run.context["testDecision"]
    assert decision["action"] == "skip"
    assert decision["reason"] == REASON
    assert decision["operator"] == "dong"
    assert decision["reportArtifactId"] == report_id
    assert any(REASON in note for note in run.recovery_notes)
    assert len(_events(run, "TESTS_SKIPPED")) == 1
    # History is not rewritten: the report still says NO_TESTS.
    assert run.item_results["T1"]["TEST_REPORT"].content["report"]["verdict"] == "NO_TESTS"
    store.close()


def test_skip_before_the_last_item_advances_to_the_next_item(tmp_path):
    engine, run, store, _gateways, _repo, sandbox = harness(
        tmp_path,
        review_replies=[review(), review()],
        exits=[5, 0],
        fix_replies=(),
        task_reply=_two_item_task(),
        implement_replies=[change(), change("extra.py", "VALUE = 2\n")],
    )
    run = _drive(engine, run)
    assert run.state.stage == TEST_ESCALATED_STAGE
    run = skip_tests(engine, run.id, reason=REASON, operator="dong")
    run = _drive(engine, run)
    assert run.state.stage == "COMPLETED", [(e.code, e.message) for e in run.errors]
    assert len(sandbox.calls) == 2
    assert run.item_results["T1"]["TEST_REPORT"].content["report"]["verdict"] == "NO_TESTS"
    assert run.item_results["T2"]["TEST_REPORT"].content["report"]["verdict"] == "PASS"
    store.close()


def test_replace_commands_retests_with_the_new_commands(tmp_path):
    engine, run, store, _gateways, _repo, sandbox = harness(
        tmp_path, review_replies=[review()], exits=[5, 0]
    )
    run = _drive(engine, run)
    assert run.state.stage == TEST_ESCALATED_STAGE
    test_stage = next(step.stage for step in engine._definition.steps if step.agent_type == "test")
    run = replace_test_commands(
        engine,
        TestCommandReplacement(
            run_id=run.id, commands=[["pytest", "-q", "tests"]], operator="dong"
        ),
    )
    assert run.state.stage == test_stage
    assert run.context["project"]["testCommands"] == [["pytest", "-q", "tests"]]
    decision = run.context["testDecision"]
    assert decision["action"] == "replace"
    assert decision["commands"] == [["pytest", "-q", "tests"]]
    assert len(_events(run, "TEST_COMMANDS_REPLACED")) == 1
    run = _drive(engine, run)
    assert run.state.stage == "COMPLETED"
    assert len(sandbox.calls) == 2
    store.close()


@pytest.mark.parametrize(
    "commands",
    [
        [[r"C:\tools\pytest.exe", "-q"]],  # absolute path: the agent rejects it
        [["pytest", ""]],  # empty argument
        [],  # no commands at all
        [["pytest"] * 300],  # argv too long
    ],
)
def test_replace_rejects_invalid_commands_without_storing(tmp_path, commands):
    engine, run, store, _gateways, _sandbox = _escalated(tmp_path)
    with pytest.raises(ValueError):
        replace_test_commands(
            engine,
            TestCommandReplacement(run_id=run.id, commands=commands, operator="dong"),
        )
    run = engine.get(run.id)
    assert run.state.stage == TEST_ESCALATED_STAGE
    assert run.context["project"]["testCommands"] == [["pytest", "-q"]]
    assert "testDecision" not in run.context
    store.close()


def test_skip_requires_a_reason(tmp_path):
    engine, run, store, _gateways, _sandbox = _escalated(tmp_path)
    with pytest.raises(ValueError):
        skip_tests(engine, run.id, reason="   ", operator="dong")
    assert engine.get(run.id).state.stage == TEST_ESCALATED_STAGE
    store.close()


def test_actions_are_rejected_away_from_the_test_stop(tmp_path):
    engine, run, store, _gateways, _sandbox = _escalated(tmp_path)
    with engine._edit(run.id) as stored:
        stored.state = stored.state.__class__(stage="CODE_FIX_ESCALATED", revisions={})
    with pytest.raises(ValueError):
        skip_tests(engine, run.id, reason=REASON, operator="dong")
    with pytest.raises(ValueError):
        replace_test_commands(
            engine,
            TestCommandReplacement(run_id=run.id, commands=[["pytest"]], operator="dong"),
        )
    store.close()
