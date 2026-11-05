"""InMemoryStore: the ExecutionStore contract without a database.

This is the store unit tests and ephemeral demos run on. It mirrors
the MariaDB store's semantics (version-guarded saves, create resets
the version and refuses duplicates, one transaction covering
executions AND approval decisions); cross-process durability is
MariaDB's job and is covered by its integration suite.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from asf.approval.models import ApprovalDecision, ApprovalRequest
from asf.orchestrator.execution import WorkflowExecution
from asf.orchestrator.ports import ConcurrentModificationError
from asf.state_machine.machine import RunState
from asf.storage.memory import InMemoryStore

NOW = datetime(2026, 11, 5, 17, 0, tzinfo=UTC)


def _execution(run_id: str, *, project_id: str = "proj-1") -> WorkflowExecution:
    return WorkflowExecution(
        id=run_id,
        task_id=f"task-{run_id}",
        project_id=project_id,
        state=RunState(stage="CREATED"),
        definition={"id": "software-development"},
        started_at=NOW,
        updated_at=NOW,
    )


def test_create_resets_version_and_get_returns_a_copy():
    store = InMemoryStore()
    run = _execution("run-1")
    run.version = 7
    store.create_execution(run)
    assert run.version == 0
    fetched = store.get_execution("run-1")
    fetched.context["project"] = {"name": "mutated"}
    assert store.get_execution("run-1").context.get("project") is None


def test_create_duplicate_id_is_refused():
    store = InMemoryStore()
    store.create_execution(_execution("run-1"))
    with pytest.raises(ValueError, match="already exists"):
        store.create_execution(_execution("run-1"))


def test_save_is_version_guarded_like_mariadb():
    store = InMemoryStore()
    store.create_execution(_execution("run-1"))
    first = store.get_execution("run-1")
    second = store.get_execution("run-1")
    first.context["n"] = 1
    store.save_execution(first)
    assert first.version == 1  # the saved copy's version bumps in place
    with pytest.raises(ConcurrentModificationError):
        store.save_execution(second)
    with pytest.raises(KeyError):
        store.save_execution(_execution("missing"))
    with pytest.raises(KeyError):
        store.get_execution("missing")


def test_transaction_rolls_back_executions_and_decisions_together():
    store = InMemoryStore()
    store.create_execution(_execution("run-1"))
    approval = ApprovalRequest(
        id="approval-1",
        task_id="task-run-1",
        workflow_id="software-development",
        project_id="proj-1",
        artifact_id="artifact-1",
        type="SPEC",
        status="PENDING",
        requested_by="orchestrator",
        requested_at=NOW,
        expires_at=None,
        min_approvals=1,
        reviewers=["one"],
        metadata={},
    )
    store.approvals.create(approval)
    with pytest.raises(RuntimeError, match="boom"), store.transaction():
        changed = store.get_execution("run-1")
        changed.context["n"] = 99
        store.save_execution(changed)
        store.create_execution(_execution("run-2"))
        store.approvals.add_decision(
            ApprovalDecision(
                approval_id="approval-1",
                reviewer="one",
                decision="APPROVED",
                created_at=NOW,
            )
        )
        raise RuntimeError("boom")
    assert store.get_execution("run-1").context.get("n") is None
    with pytest.raises(KeyError):
        store.get_execution("run-2")
    assert store.approvals.list_decisions("approval-1") == []


def test_summaries_are_light_filtered_and_paged():
    store = InMemoryStore()
    store.create_execution(_execution("run-1"))
    failed = _execution("run-2")
    failed.state = RunState(stage="FAILED")
    store.create_execution(failed)
    store.create_execution(_execution("run-3", project_id="other"))
    rows = store.list_execution_summaries("proj-1")
    assert {row["id"] for row in rows} == {"run-1", "run-2"}
    assert all("payload" not in row for row in rows)
    assert rows[0]["workflowId"] == "software-development"
    assert [r["id"] for r in store.list_execution_summaries(status="FAILED")] == ["run-2"]
    assert [r["id"] for r in store.list_execution_summaries(limit=1)] == ["run-1"]
    assert store.list_execution_summaries("nope") == []


def test_list_executions_filters_by_project_sorted_by_id():
    store = InMemoryStore()
    store.create_execution(_execution("run-b"))
    store.create_execution(_execution("run-a"))
    store.create_execution(_execution("run-c", project_id="other"))
    assert [r.id for r in store.list_executions("proj-1")] == ["run-a", "run-b"]
