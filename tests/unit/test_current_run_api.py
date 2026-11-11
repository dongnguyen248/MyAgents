"""One current run feeds every task surface (Stage 5).

The lineages below are fabricated by direct state injection (the
operator-controls idiom): tracked order, started_at order and
updated_at order disagree, and one run is cancelled after a newer
run started — the shape that made the task page show one run's
status above another run's steps, banner and action buttons.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from asf.api.demo import build_demo
from asf.contracts.models import PlatformError
from asf.state_machine.machine import RunState

BASE = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)


def _at(hours: int) -> datetime:
    return BASE + timedelta(hours=hours)


def _iso(hours: int) -> str:
    return _at(hours).isoformat()


def _error(code: str, hours: int) -> PlatformError:
    return PlatformError(
        code=code,
        message=f"{code} happened",
        category="INTEGRATION",
        retryable=True,
        timestamp=_at(hours),
    )


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    service, engine, store = build_demo(tmp_path_factory.mktemp("current-run"), ephemeral=True)
    return service, engine, store


def _fabricate(
    service: Any,
    engine: Any,
    store: Any,
    task_id: str,
    *,
    started: int,
    updated: int,
    stage: str | None = None,
    errors: tuple[PlatformError, ...] = (),
    split: dict[str, Any] | None = None,
) -> str:
    run = engine.start(
        task_id=task_id,
        project_id="vhpc",
        inputs={"spec": {"requirement": "Build it"}},
    )
    service.track(run.id)
    # Written through the store on purpose: an engine save stamps
    # updated_at with the engine clock, which would destroy the
    # fabricated orderings these tests exist to pin.
    stored = store.get_execution(run.id)
    stored.started_at = _at(started)
    stored.updated_at = _at(updated)
    if stage is not None:
        stored.state = RunState(stage=stage, revisions={})
    stored.errors = list(errors)
    if split is not None:
        stored.context["split"] = split
    store.save_execution(stored)
    service._invalidate_runs_cache()
    return run.id


def test_all_surfaces_agree_on_the_current_run(demo) -> None:
    service, engine, store = demo
    _fabricate(service, engine, store, "task-multi", started=1, updated=9, stage="CANCELLED")
    _fabricate(service, engine, store, "task-multi", started=2, updated=2, stage="COMPLETED")
    failed = _fabricate(
        service,
        engine,
        store,
        "task-multi",
        started=3,
        updated=3,
        stage="FAILED",
        errors=(_error("LLM_BAD_REQUEST", 3),),
    )
    task = service.get_task("task-multi")
    assert task is not None
    assert task["currentRunId"] == failed
    assert task["status"] == "FAILED"
    row = next(row for row in service.list_tasks() if row["id"] == "task-multi")
    assert row["currentRunId"] == failed
    workflow = service.get_workflow("task-multi")
    assert workflow is not None
    assert workflow["id"] == failed
    # The banner is the current run's own last error, not an older
    # run's — the lineage's first run was touched most recently.
    assert workflow["error"]["code"] == "LLM_BAD_REQUEST"


def test_running_current_run_with_copied_errors_shows_no_banner(demo) -> None:
    service, engine, store = demo
    legacy = _error("SANDBOX_ERROR", 1)
    _fabricate(
        service, engine, store, "task-live", started=1, updated=1, stage="FAILED", errors=(legacy,)
    )
    # A resume fork copies the source run's errors; while it is live
    # those copied errors must not surface as a failure banner.
    current = _fabricate(
        service, engine, store, "task-live", started=2, updated=2, errors=(legacy,)
    )
    workflow = service.get_workflow("task-live")
    assert workflow is not None
    assert workflow["id"] == current
    assert workflow["status"] != "FAILED"
    assert workflow["error"] is None
    task = service.get_task("task-live")
    assert task is not None and task["currentRunId"] == current


def test_late_update_of_an_old_run_no_longer_tops_the_list(demo) -> None:
    service, engine, store = demo
    _fabricate(service, engine, store, "task-other", started=0, updated=5, stage="COMPLETED")
    rows = service.list_tasks()
    ids = [row["id"] for row in rows]
    # task-multi's oldest run was updated at hour 9, but its current
    # run was updated at hour 3 — the row stays below task-other
    # (hour 5). Before the single pick, the late update moved the
    # task to the top of the list.
    assert ids.index("task-other") < ids.index("task-multi")
    row = next(row for row in rows if row["id"] == "task-multi")
    assert row["updatedAt"] == _iso(3)


def test_since_hours_filter_applies_over_the_new_pick(demo) -> None:
    service, _engine, _store = demo
    recent = service.list_tasks({"sinceHours": 1})
    assert all(row["id"] != "task-multi" for row in recent)
    everything = service.list_tasks({"sinceHours": 24 * 400})
    assert any(row["id"] == "task-multi" for row in everything)


def test_split_parent_current_run_with_interleaved_parts(demo) -> None:
    service, engine, store = demo
    split_one = {"parentTaskId": "task-split", "index": 1, "total": 2, "title": "Big"}
    split_two = {"parentTaskId": "task-split", "index": 2, "total": 2, "title": "Big"}
    _fabricate(
        service,
        engine,
        store,
        "task-split-part-1",
        started=1,
        updated=8,
        stage="COMPLETED",
        split=split_one,
    )
    _fabricate(
        service,
        engine,
        store,
        "task-split-part-2",
        started=3,
        updated=3,
        stage="COMPLETED",
        split=split_two,
    )
    newest = _fabricate(
        service,
        engine,
        store,
        "task-split-part-1",
        started=5,
        updated=5,
        stage="COMPLETED",
        split=split_one,
    )
    parent = service.get_task("task-split")
    assert parent is not None
    assert parent["isSplitParent"] is True
    # Part 1's second attempt started after part 2's run: it is the
    # parent's current run even though part 1's first attempt carries
    # the latest update of the whole family.
    assert parent["currentRunId"] == newest
    part_one = service.get_task("task-split-part-1")
    assert part_one is not None and part_one["currentRunId"] == newest


def test_single_run_task_is_unchanged(demo) -> None:
    service, engine, store = demo
    only = _fabricate(
        service, engine, store, "task-single", started=1, updated=1, stage="COMPLETED"
    )
    task = service.get_task("task-single")
    assert task is not None and task["currentRunId"] == only
    workflow = service.get_workflow("task-single")
    assert workflow is not None and workflow["id"] == only
