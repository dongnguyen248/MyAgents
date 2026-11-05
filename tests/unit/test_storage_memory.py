from __future__ import annotations

import unittest
from datetime import UTC, datetime

from asf.approval.models import ApprovalDecision, ApprovalRequest
from asf.storage.memory import InMemoryApprovalRepository

T1 = datetime(2026, 10, 20, 10, 0, 0, tzinfo=UTC)
T2 = datetime(2026, 10, 20, 11, 0, 0, tzinfo=UTC)
T3 = datetime(2026, 10, 20, 12, 0, 0, tzinfo=UTC)


def make_request(
    approval_id: str,
    task_id: str = "task-1",
    status: str = "PENDING",
    requested_at: datetime = T1,
) -> ApprovalRequest:
    return ApprovalRequest(
        id=approval_id,
        task_id=task_id,
        workflow_id="wf-1",
        project_id="p-1",
        artifact_id="art-1",
        type="SPEC",
        status=status,  # type: ignore[arg-type]
        requested_by="orch",
        requested_at=requested_at,
        expires_at=None,
        min_approvals=1,
        reviewers=["r1"],
        metadata={"note": "original"},
    )


class InMemoryApprovalRepositoryTests(unittest.TestCase):
    def test_copy_semantics_on_create_and_get(self):
        repo = InMemoryApprovalRepository()
        req = make_request("app-1")
        created = repo.create(req)

        # Mutate the dictionary of the created object
        created.metadata["note"] = "mutated"

        retrieved = repo.get("app-1")
        self.assertIsNotNone(retrieved)
        assert retrieved is not None
        self.assertEqual(retrieved.metadata["note"], "original")

        # Mutate the retrieved dictionary
        retrieved.metadata["note"] = "mutated_again"
        retrieved2 = repo.get("app-1")
        assert retrieved2 is not None
        self.assertEqual(retrieved2.metadata["note"], "original")

    def test_update_unknown_id_raises_key_error(self):
        repo = InMemoryApprovalRepository()
        req = make_request("unknown-app")
        with self.assertRaises(KeyError):
            repo.update(req)

    def test_update_copy_semantics(self):
        repo = InMemoryApprovalRepository()
        req = make_request("app-1")
        repo.create(req)

        updated = req.model_copy(update={"status": "APPROVED", "metadata": {"note": "v2"}})
        returned = repo.update(updated)
        returned.metadata["note"] = "mutated_returned"

        fetched = repo.get("app-1")
        assert fetched is not None
        self.assertEqual(fetched.status, "APPROVED")
        self.assertEqual(fetched.metadata["note"], "v2")

    def test_ordering_list_pending(self):
        repo = InMemoryApprovalRepository()
        # Add in non-sorted order
        repo.create(make_request("b", requested_at=T2))
        repo.create(make_request("c", requested_at=T1))
        repo.create(make_request("a", requested_at=T1))
        repo.create(make_request("d", status="APPROVED", requested_at=T1))  # Not pending

        pending = repo.list_pending()
        self.assertEqual([r.id for r in pending], ["a", "c", "b"])

    def test_ordering_list_by_task(self):
        repo = InMemoryApprovalRepository()
        repo.create(make_request("b", task_id="task-1", requested_at=T2))
        repo.create(make_request("other", task_id="task-2", requested_at=T1))
        repo.create(make_request("c", task_id="task-1", requested_at=T1))
        repo.create(make_request("a", task_id="task-1", requested_at=T1))

        by_task = repo.list_by_task("task-1")
        self.assertEqual([r.id for r in by_task], ["a", "c", "b"])

    def test_decisions_kept_per_approval_and_ordered(self):
        repo = InMemoryApprovalRepository()
        d1 = ApprovalDecision(
            approval_id="app-1",
            decision="REQUEST_CHANGES",
            reviewer="r1",
            comment="fix 1",
            created_at=T1,
        )
        d2 = ApprovalDecision(
            approval_id="app-2",
            decision="APPROVED",
            reviewer="r2",
            comment="ok",
            created_at=T2,
        )
        d3 = ApprovalDecision(
            approval_id="app-1",
            decision="APPROVED",
            reviewer="r1",
            comment="fixed",
            created_at=T3,
        )

        repo.add_decision(d1)
        repo.add_decision(d2)
        repo.add_decision(d3)

        decisions_app1 = repo.list_decisions("app-1")
        self.assertEqual(len(decisions_app1), 2)
        self.assertEqual(decisions_app1[0].comment, "fix 1")
        self.assertEqual(decisions_app1[1].comment, "fixed")

        decisions_app2 = repo.list_decisions("app-2")
        self.assertEqual(len(decisions_app2), 1)
        self.assertEqual(decisions_app2[0].comment, "ok")

        self.assertEqual(repo.list_decisions("app-unknown"), [])
