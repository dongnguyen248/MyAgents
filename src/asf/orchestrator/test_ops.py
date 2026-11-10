"""Operator decisions for a run parked at TEST_ESCALATED.

A NO_TESTS report is not a code failure: nothing was collected,
so there is nothing for a Fix agent to repair. The operator
either replaces the run's test commands and retests, or skips
the test step for this run with a recorded reason. Both actions
are human-only — they exist solely as operator operations behind
the escalation HTTP surface; no agent can reach them, and in
particular not the AI reviewer, which only ever decides approval
gates (the code loop forbids the test step from being one).

Both record the decision on the run itself: appended to the
append-only ``context["testDecisions"]`` list (one entry per
stopped item, so a multi-item run keeps every decision) and
mirrored to ``context["testDecision"]`` as the latest — the
change-request description builder reads the list so a merge
request states every skip. Both also append an audit note and
emit an event carrying argv and reason only — never sandbox
output.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from asf.agents._shared.security import redact_text
from asf.agents.test.agent import checked_test_commands
from asf.orchestrator.code_loop import TEST_ESCALATED_STAGE
from asf.state_machine.machine import apply
from asf.state_machine.triggers import Trigger
from asf.tools.ports import CommandSpec

if TYPE_CHECKING:
    from asf.orchestrator.engine import Orchestrator
    from asf.orchestrator.execution import WorkflowExecution

__all__ = [
    "SkipApplication",
    "SkipRequest",
    "TestCommandReplacement",
    "apply_skip_decision",
    "record_decision",
    "replace_test_commands",
    "run_scoped_skip",
    "skip_tests",
]

RUN_SCOPED_SKIP_KEY = "testSkipRemaining"


@dataclass(frozen=True)
class TestCommandReplacement:
    """An operator's replacement test commands for one stopped run."""

    run_id: str
    commands: object
    operator: str = "operator"
    reason: str | None = None


@dataclass(frozen=True)
class SkipApplication:
    """One application of a test-skip decision to the current item.

    ``via`` is "operator" for the decision the operator makes at a
    stop and "run-scope" when the engine applies a run-scoped
    decision the operator recorded earlier; ``scope`` is the scope
    the operator chose at the stop ("item" unless they explicitly
    picked the rest of the run).
    """

    reason: str
    operator: str
    via: str = "operator"
    scope: str = "item"


def _require_test_escalation(run: WorkflowExecution, action: str) -> None:
    if run.state.stage != TEST_ESCALATED_STAGE:
        raise ValueError(
            f"Run is at {run.state.stage}, not {TEST_ESCALATED_STAGE}; "
            f"only a run stopped for a NO_TESTS decision can be {action}"
        )


def record_decision(
    engine: Orchestrator, run: WorkflowExecution, decision: dict[str, Any]
) -> dict[str, Any]:
    """Append a test decision to the run's audit list; return the entry.

    The list is the durable record (one entry per stopped item);
    the singular ``testDecision`` mirrors the latest entry for the
    readers that only need the most recent decision.
    """
    report = run.artifacts.get("TEST_REPORT")
    entry = {
        **decision,
        "itemId": _current_item(run),
        "at": engine._now().isoformat(),
        "reportArtifactId": report.id if report is not None else None,
    }
    entry.setdefault("via", "operator")
    history = run.context.get("testDecisions")
    if not isinstance(history, list):
        history = []
        run.context["testDecisions"] = history
    history.append(entry)
    run.context["testDecision"] = entry
    return entry


def _current_item(run: WorkflowExecution) -> str | None:
    if run.task_order and 0 <= run.item_index < len(run.task_order):
        return run.task_order[run.item_index]
    return None


def apply_skip_decision(
    engine: Orchestrator, run: WorkflowExecution, application: SkipApplication
) -> None:
    """Record a skip for the current item and advance like a pass.

    Shared by the operator action at a stop and by the engine's
    run-scoped path, which applies the operator's recorded decision
    to a later item — the decision entry, the audit note and the
    event are written the same way either way, with ``via`` saying
    which path applied it.
    """
    decision: dict[str, Any] = {
        "action": "skip",
        "operator": application.operator,
        "reason": application.reason,
        "via": application.via,
    }
    record_decision(engine, run, decision)
    run.recovery_notes.append(f"Tests skipped by {application.operator}: {application.reason}")
    metadata: dict[str, Any] = {"operator": application.operator}
    if application.via != "operator":
        metadata["via"] = application.via
    if application.scope != "item":
        metadata["scope"] = application.scope
    engine._event(
        run,
        "TESTS_SKIPPED",
        f"Operator skipped the test step: {application.reason}",
        metadata=metadata,
    )
    if not (run.task_order and engine._next_item(run)):
        run.state = apply(engine._graph, run.state, Trigger.COMPLETE)


@dataclass(frozen=True)
class SkipRequest:
    """An operator's test skip for one stopped run."""

    run_id: str
    reason: str
    operator: str = "operator"
    scope: str = "item"


def skip_tests(engine: Orchestrator, request: SkipRequest) -> WorkflowExecution:
    """Skip this run's test step and advance exactly like a pass.

    The TEST_REPORT keeps its NO_TESTS verdict — history is not
    rewritten; the skip lives on the run record. The reason is
    mandatory: a skip nobody explained must not be possible. With
    scope "run" the same decision is also recorded as the run's
    standing skip (``testSkipRemaining``), which the engine later
    applies to any further item whose tests collect nothing; the
    default scope "item" decides only the stopped item.
    """
    cleaned = request.reason.strip()
    if not cleaned:
        raise ValueError("Skipping tests requires a non-empty reason")
    if request.scope not in ("item", "run"):
        raise ValueError("scope must be 'item' or 'run'")
    with engine._edit(request.run_id) as run:
        _require_test_escalation(run, "skipped")
        if request.scope == "run":
            run.context[RUN_SCOPED_SKIP_KEY] = {
                "reason": cleaned,
                "operator": request.operator,
                "at": engine._now().isoformat(),
                "itemId": _current_item(run),
            }
        apply_skip_decision(
            engine,
            run,
            SkipApplication(reason=cleaned, operator=request.operator, scope=request.scope),
        )
    return engine.get(request.run_id)


def run_scoped_skip(run: WorkflowExecution) -> SkipApplication | None:
    """The run's standing skip decision, if the operator recorded one."""
    flag = run.context.get(RUN_SCOPED_SKIP_KEY)
    if not isinstance(flag, dict):
        return None
    reason = str(flag.get("reason") or "").strip()
    if not reason:
        return None
    return SkipApplication(
        reason=reason,
        operator=str(flag.get("operator") or "operator"),
        via="run-scope",
    )


def replace_test_commands(
    engine: Orchestrator, request: TestCommandReplacement
) -> WorkflowExecution:
    """Replace the run's baked test commands and retest.

    Commands are validated with the Test agent's strict argv rules
    BEFORE anything is stored, so a bad replacement is rejected
    instead of failing on the re-run. The override is run-scoped:
    the run's own baked context changes; the project profile does
    not, so a later Run again still bakes the profile's commands.
    Replacing the commands also clears any run-scoped test skip —
    a working command set supersedes the skip decision — and the
    clearing is recorded on the event.
    """
    specs = checked_test_commands(request.commands)
    operator = request.operator
    with engine._edit(request.run_id) as run:
        _require_test_escalation(run, "retested with new commands")
        project = dict(run.context.get("project") or {})
        project["testCommands"] = [list(spec.argv) for spec in specs]
        run.context["project"] = project
        record_decision(engine, run, _replace_decision(specs, operator, request.reason))
        cleared = run.context.pop(RUN_SCOPED_SKIP_KEY, None) is not None
        joined = redact_text("; ".join(" ".join(spec.argv) for spec in specs))
        note = f"Test commands replaced by {operator}: {joined}"
        if cleared:
            note += "; the run-scoped test skip was cleared"
        run.recovery_notes.append(note)
        metadata: dict[str, Any] = {"operator": operator}
        if cleared:
            metadata["clearedRunScopeSkip"] = True
        engine._event(
            run,
            "TEST_COMMANDS_REPLACED",
            f"Operator replaced the test commands: {joined}",
            metadata=metadata,
        )
        run.state = apply(engine._graph, run.state, Trigger.RESUME)
    return engine.get(request.run_id)


def _replace_decision(
    specs: tuple[CommandSpec, ...], operator: str, reason: str | None
) -> dict[str, Any]:
    decision: dict[str, Any] = {
        "action": "replace",
        "operator": operator,
        "commands": [list(spec.argv) for spec in specs],
    }
    if reason is not None and reason.strip():
        decision["reason"] = reason.strip()
    return decision
