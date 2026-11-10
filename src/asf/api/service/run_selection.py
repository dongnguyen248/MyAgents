"""The single definition of a task's current run.

Every surface that shows "the run" of a task must agree on one run:
the task list row, the task page header, the workflow lookup by task
id and the dashboard's own pick. Before this module each surface
chose differently (most recently updated, last in tracked order,
newest started by string sort), so one page could show one run's
status above another run's steps, error banner and action buttons.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from asf.orchestrator.execution import WorkflowExecution

RunPredicate = Callable[["WorkflowExecution"], bool]


def select_current_run(
    runs: Sequence[WorkflowExecution],
    matches: RunPredicate,
) -> WorkflowExecution | None:
    """The current run among the runs accepted by `matches`.

    The winner is the maximum by (started_at, updated_at, position):
    the most recently started run, with the later update and then
    the later tracked position breaking ties. A late update or
    cancellation of an older run therefore never makes it current
    again, and the result is deterministic for equal timestamps.
    """
    best: WorkflowExecution | None = None
    best_key: tuple[datetime, datetime, int] | None = None
    for index, run in enumerate(runs):
        if not matches(run):
            continue
        key = (run.started_at, run.updated_at, index)
        if best_key is None or key > best_key:
            best = run
            best_key = key
    return best


def task_run(task_id: str) -> RunPredicate:
    """Accept runs that belong to the task itself."""

    def matches(run: WorkflowExecution) -> bool:
        return run.task_id == task_id

    return matches


def split_part_run(parent_task_id: str) -> RunPredicate:
    """Accept runs that are auto-split parts of the parent task."""

    def matches(run: WorkflowExecution) -> bool:
        split = run.context.get("split") if isinstance(run.context, Mapping) else None
        return isinstance(split, Mapping) and split.get("parentTaskId") == parent_task_id

    return matches
