"""The current-run selector: one run feeds every task surface.

The fixture orderings are adversarial on purpose — tracked order,
started_at order and updated_at order disagree — because that is
exactly the resume-lineage shape that made the task page compose
its header, steps and banner from different runs.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from asf.api.service.run_selection import (
    select_current_run,
    split_part_run,
    task_run,
)
from asf.orchestrator.execution import WorkflowExecution
from asf.state_machine.machine import RunState

BASE = datetime(2026, 11, 10, 0, 0, tzinfo=UTC)


def _at(hours: int) -> datetime:
    return BASE + timedelta(hours=hours)


def _run(
    run_id: str,
    *,
    started: int,
    updated: int,
    task_id: str = "task-1",
    context: dict[str, Any] | None = None,
) -> WorkflowExecution:
    return WorkflowExecution(
        id=run_id,
        task_id=task_id,
        project_id="proj-1",
        state=RunState(stage="SPEC", revisions={}),
        definition={"id": "software-development"},
        started_at=_at(started),
        updated_at=_at(updated),
        context=context or {},
    )


def test_no_runs_and_no_match_return_none() -> None:
    run = _run("r1", started=1, updated=1)
    assert select_current_run([], task_run("task-1")) is None
    assert select_current_run([run], task_run("other-task")) is None


def test_single_run_is_current() -> None:
    run = _run("r1", started=1, updated=1)
    assert select_current_run([run], task_run("task-1")) is run


def test_newest_started_wins_when_all_orders_disagree() -> None:
    # Tracked order, started order and updated order all differ:
    # the run that started last is current, however late the older
    # runs were touched afterwards.
    newest_started = _run("r-new", started=5, updated=5)
    late_updated = _run("r-updated", started=3, updated=9)
    late_tracked = _run("r-tracked", started=1, updated=2)
    runs = [late_updated, late_tracked, newest_started]
    assert select_current_run(runs, task_run("task-1")) is newest_started
    runs.reverse()
    assert select_current_run(runs, task_run("task-1")) is newest_started


def test_older_run_cancelled_after_newer_started_stays_not_current() -> None:
    older = _run("r-old", started=1, updated=8)
    newer = _run("r-new", started=4, updated=4)
    assert select_current_run([older, newer], task_run("task-1")) is newer


def test_equal_started_at_falls_to_updated_at() -> None:
    first = _run("r-first", started=3, updated=3)
    touched = _run("r-touched", started=3, updated=6)
    assert select_current_run([first, touched], task_run("task-1")) is touched
    assert select_current_run([touched, first], task_run("task-1")) is touched


def test_equal_timestamps_fall_to_tracked_position() -> None:
    first = _run("r-first", started=3, updated=3)
    second = _run("r-second", started=3, updated=3)
    assert select_current_run([first, second], task_run("task-1")) is second
    assert select_current_run([second, first], task_run("task-1")) is first


def test_other_tasks_runs_are_ignored() -> None:
    mine = _run("r-mine", started=1, updated=1)
    theirs = _run("r-theirs", started=9, updated=9, task_id="task-2")
    assert select_current_run([mine, theirs], task_run("task-1")) is mine


def test_split_part_predicate_matches_only_that_parents_parts() -> None:
    part = _run(
        "r-part",
        started=2,
        updated=2,
        task_id="parent-part-1",
        context={"split": {"parentTaskId": "parent", "index": 1, "total": 2}},
    )
    other_part = _run(
        "r-other",
        started=5,
        updated=5,
        task_id="other-part-1",
        context={"split": {"parentTaskId": "other", "index": 1, "total": 2}},
    )
    plain = _run("r-plain", started=9, updated=9, task_id="parent")
    malformed = _run("r-bad", started=8, updated=8, context={"split": "nope"})
    runs = [part, other_part, plain, malformed]
    assert select_current_run(runs, split_part_run("parent")) is part
