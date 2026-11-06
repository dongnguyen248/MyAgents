"""The demo backend's ``--selftest`` driver.

Drives one run to completion against the demo service: AI-mode
gates are decided by the review loop itself (just tick); only a
gate addressed to human reviewers is approved directly, as
'dashboard'. Kept out of ``demo.py`` so that module does not
grow with the selftest's race handling.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from asf.approval.models import AI_REVIEWER
from asf.state_machine.machine import InvalidTransition

if TYPE_CHECKING:
    from asf.api.service import FactoryService
    from asf.orchestrator.engine import Orchestrator

__all__ = ["MAX_TOLERATED_TICK_RACES", "run_selftest"]

MAX_TOLERATED_TICK_RACES = 3


def _selftest_advance(service: FactoryService, engine: Orchestrator, run: Any) -> None:
    """One selftest step: tick, or approve a human-addressed gate."""
    if run.approval_id is None:
        service.tick_run(run.id)
        return
    pending = engine.pending_approval(run.id)
    if AI_REVIEWER in pending.reviewers:
        service.tick_run(run.id)
    else:
        service.decide_approval(pending.id, decision="APPROVE")


def _selftest_inputs() -> dict[str, Any]:
    return {
        "spec": {"requirement": "Demonstrate the dashboard backend end to end"},
        "implement": {"taskItemId": "T1", "ref": "main"},
        "review": {"taskItemId": "T1", "ref": "main"},
        "test": {"taskItemId": "T1", "ref": "main"},
    }


def _selftest_report(run: Any, races: int) -> int:
    artifact_types = {artifact.type for artifact in run.artifact_history.values()}
    missing = {"SPEC", "PLAN", "TASK", "CODE"} - artifact_types
    if races > MAX_TOLERATED_TICK_RACES:
        print(f"SELFTEST FAILED: {races} tick races tolerated (max {MAX_TOLERATED_TICK_RACES})")
        return 1
    if run.state.stage != "COMPLETED" or missing:
        print(f"SELFTEST FAILED: stage={run.state.stage} missing={sorted(missing)}")
        for error in run.errors:
            print(f"error: {error.code}: {error.message}")
        return 1
    print(f"SELFTEST OK - final stage: {run.state.stage} (tolerated {races} tick races)")
    return 0


def run_selftest(service: FactoryService, engine: Orchestrator) -> int:
    """Drive one run to completion (see the module docstring)."""
    project_id = service.list_projects()[0]["id"]
    run = service.start_run(
        "demo-task",
        project_id,
        inputs=_selftest_inputs(),
        context={"project": {"testCommands": [["python", "-m", "pytest", "-q"]]}},
    )
    races = 0
    for _ in range(100):
        run = engine.get(run.id)
        print(f"stage: {run.state.stage}")
        if run.state.stage in ("COMPLETED", "FAILED", "CANCELLED"):
            break
        # The background drive advances the run concurrently, so a
        # tick can lose the race against a run that just completed:
        # engine.tick raises InvalidTransition on a terminal run.
        # That is the ONLY tolerated race — the decide path touches
        # human-addressed gates only, which nothing else can decide
        # or close, so an ApprovalError there would be a real bug.
        try:
            _selftest_advance(service, engine, run)
        except InvalidTransition:
            races += 1
    service.wait_for_drives()
    return _selftest_report(engine.get(run.id), races)
