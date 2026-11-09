"""Item 5: a NO_TESTS test report parks the run for the operator.

The rework harness drives the real agents; a sandbox exit of 5 on
the harness's pytest command makes the real Test agent publish a
NO_TESTS report. Routing must escalate to TEST_ESCALATED without
dispatching Fix and without spending any of the fix budget.
"""

from __future__ import annotations

import pytest

from asf.orchestrator.code_loop import FIX_STEP, TEST_ESCALATED_STAGE
from asf.state_machine.triggers import StageKind, Trigger
from tests.integration.test_orchestrator_rework import harness, review

_STOPS = ("COMPLETED", "FAILED", "CODE_FIX_ESCALATED", "TEST_ESCALATED")


def _drive(engine, run, *, limit=50):
    for _ in range(limit):
        if run.state.stage in _STOPS:
            return run
        if run.approval_id:
            run = engine.decide(run.id, reviewer="reviewer", decision="APPROVED")
        else:
            run = engine.tick(run.id)
    pytest.fail("Orchestrator did not reach a bounded stop")


def test_no_tests_escalates_without_spending_fix_budget(tmp_path):
    engine, run, store, gateways, _repository, sandbox = harness(
        tmp_path,
        review_replies=[review()],
        exits=[5],
    )
    run = _drive(engine, run)
    assert run.state.stage == TEST_ESCALATED_STAGE
    assert run.errors == []
    # No Fix dispatch, no revision spent, exactly one test run.
    assert gateways["fix"].requests == []
    assert run.state.revisions.get(FIX_STEP, 0) == 0
    assert len(sandbox.calls) == 1
    report = run.artifacts["TEST_REPORT"]
    assert report.content["report"]["verdict"] == "NO_TESTS"
    escalations = [
        obs.event
        for obs in run.observations
        if obs.event is not None and obs.event.event_type == "WORKFLOW_ESCALATED"
    ]
    assert len(escalations) == 1
    assert escalations[0].metadata["reason"] == "NO_TESTS"
    assert "pytest -q" in escalations[0].message
    store.close()


def test_pinned_definition_picks_up_the_test_escalation_stage(tmp_path):
    """Loop stages are synthesised at engine construction, not stored.

    The harness builds its definition from the shipped YAML — the
    same data an older stored run pins — and that definition has no
    TEST_ESCALATED step, yet the engine's graph must carry the
    stage and its edges (the Phase 12 precedent).
    """
    engine, run, store, _gateways, _repository, _sandbox = harness(
        tmp_path,
        review_replies=[review()],
        exits=[5],
    )
    definition = engine._definition
    assert all(step.stage != TEST_ESCALATED_STAGE for step in definition.steps)
    graph = engine._graph
    stages = {stage.name: stage for stage in graph.stages}
    assert TEST_ESCALATED_STAGE in stages
    assert stages[TEST_ESCALATED_STAGE].kind is StageKind.ESCALATED
    steps = {step.id: step for step in definition.steps}
    test_stage_name = steps[stages[TEST_ESCALATED_STAGE].step_id].stage
    edges = {(edge.source, edge.trigger, edge.target) for edge in graph.edges}
    assert (test_stage_name, Trigger.ESCALATE, TEST_ESCALATED_STAGE) in edges
    assert (TEST_ESCALATED_STAGE, Trigger.RESUME, test_stage_name) in edges
    own_exit = next(
        edge.target
        for edge in graph.edges
        if edge.source == test_stage_name and edge.trigger is Trigger.COMPLETE
    )
    assert (TEST_ESCALATED_STAGE, Trigger.COMPLETE, own_exit) in edges
    store.close()
