"""Routing of review/test verdicts inside the code loop.

Kept beside the engine (the ``ai_review_apply`` pattern) so
``Orchestrator._apply_result`` stays small: the engine validates the
artifact shape, then hands a code-loop review/test result here.
Verdicts route exactly as they always have — the expected verdict
completes (or advances to the next task item), anything else asks
for a fix — with one addition: a test report of NO_TESTS (pytest
ran and collected nothing) is not a failure code can fix, so the
run escalates to the operator at TEST_ESCALATED instead of
spending fix budget. No Fix dispatch, no revision spent. If the
operator has recorded a run-scoped skip for this run, that
recorded decision is applied to the item instead of parking
again (see ``asf.orchestrator.test_ops``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from asf.agents._shared.security import redact_text
from asf.agents.test.agent import PYTEST_NO_TESTS_EXIT_CODE
from asf.contracts.models import AgentResult
from asf.orchestrator.execution import WorkflowExecution
from asf.orchestrator.test_ops import apply_skip_decision, run_scoped_skip
from asf.state_machine.machine import apply
from asf.state_machine.triggers import Trigger
from asf.workflow.definition import WorkflowStepDef

if TYPE_CHECKING:
    from asf.orchestrator.engine import Orchestrator

_ALLOWED_VERDICTS = {
    "review": ("APPROVE", "CHANGES_REQUESTED"),
    "test": ("PASS", "FAIL", "NO_TESTS"),
}
_EXPECTED_VERDICTS = {"review": "APPROVE", "test": "PASS"}


def apply_quality_result(
    engine: Orchestrator,
    run: WorkflowExecution,
    step: WorkflowStepDef,
    result: AgentResult,
) -> None:
    """Validate and route one code-loop review/test result."""
    verdict = result.output.get("verdict") if isinstance(result.output, dict) else None
    if verdict not in _ALLOWED_VERDICTS[step.agent_type or ""]:
        engine._fail(run, "VALIDATION_FAILED", "Invalid quality verdict", "VALIDATION")
        return
    if not engine._linked_output(run, step, result):
        return
    engine._publish_artifacts(run, result)
    run.retry_attempts = 0
    _route_verdict(engine, run, step, result)


def _route_verdict(
    engine: Orchestrator,
    run: WorkflowExecution,
    step: WorkflowStepDef,
    result: AgentResult,
) -> None:
    verdict = result.output.get("verdict") if isinstance(result.output, dict) else None
    if verdict == "NO_TESTS":
        _handle_no_tests(engine, run, result)
    elif verdict != _EXPECTED_VERDICTS[step.agent_type or ""]:
        engine._request_fix(run)
    elif step.agent_type == "test" and engine._next_item(run):
        return
    else:
        run.state = apply(engine._graph, run.state, Trigger.COMPLETE)


def _handle_no_tests(engine: Orchestrator, run: WorkflowExecution, result: AgentResult) -> None:
    """Apply the run's standing skip if one is recorded, else park.

    This branch is only reached on a NO_TESTS verdict, which the
    Test agent produces solely for a pytest-recognisable command
    that collected nothing (exit 5) — so a standing skip can never
    suppress a real test result. Without one, the run parks for a
    fresh operator decision, exactly as before.
    """
    standing = run_scoped_skip(run)
    if standing is not None:
        apply_skip_decision(engine, run, standing)
        return
    escalate_no_tests(engine, run, result)


def escalate_no_tests(engine: Orchestrator, run: WorkflowExecution, result: AgentResult) -> None:
    """Park the run for an operator decision; no fix is requested."""
    argv = _no_tests_argv(result.output)
    run.state = apply(engine._graph, run.state, Trigger.ESCALATE)
    engine._event(
        run,
        "WORKFLOW_ESCALATED",
        f"No tests were collected by '{argv}' (pytest exit 5) — waiting for operator",
        metadata={"reason": "NO_TESTS"},
    )


def _no_tests_argv(output: object) -> str:
    """The argv of the first command that collected nothing.

    The report is the agent's own output; only the argv is quoted
    (redacted like every other surfaced command line) — never the
    command's stdout/stderr.
    """
    commands = output.get("commands") if isinstance(output, dict) else None
    if not isinstance(commands, list):
        return "the configured test command"
    entry = next((item for item in commands if _collects_nothing(item)), None)
    argv = entry.get("argv") if isinstance(entry, dict) else None
    if isinstance(argv, list) and argv:
        return redact_text(" ".join(str(part) for part in argv))
    return "the configured test command"


def _collects_nothing(entry: object) -> bool:
    if not isinstance(entry, dict) or entry.get("exitCode") != PYTEST_NO_TESTS_EXIT_CODE:
        return False
    argv = entry.get("argv")
    return isinstance(argv, list) and bool(argv)
