from __future__ import annotations

import copy

from asf.approval.models import ApprovalDecision, ApprovalRequest

__all__ = ["InMemoryApprovalRepository"]


class InMemoryApprovalRepository:
    """In-memory implementation of ApprovalRepository protocol.

    Stores deep copies and returns deep copies so mutations outside the repository
    never affect internal state.

    Updating an unknown approval id raises KeyError.
    """

    def __init__(self) -> None:
        self._approvals: dict[str, ApprovalRequest] = {}
        self._decisions: dict[str, list[ApprovalDecision]] = {}

    def create(self, approval: ApprovalRequest) -> ApprovalRequest:
        self._approvals[approval.id] = copy.deepcopy(approval)
        return copy.deepcopy(approval)

    def get(self, approval_id: str) -> ApprovalRequest | None:
        approval = self._approvals.get(approval_id)
        if approval is None:
            return None
        return copy.deepcopy(approval)

    def update(self, approval: ApprovalRequest) -> ApprovalRequest:
        if approval.id not in self._approvals:
            raise KeyError(f"ApprovalRequest with id '{approval.id}' does not exist")
        self._approvals[approval.id] = copy.deepcopy(approval)
        return copy.deepcopy(approval)

    def list_by_task(self, task_id: str) -> list[ApprovalRequest]:
        matching = [
            req for req in self._approvals.values() if req.task_id == task_id
        ]
        matching.sort(key=lambda r: (r.requested_at, r.id))
        return [copy.deepcopy(r) for r in matching]

    def list_pending(self) -> list[ApprovalRequest]:
        matching = [
            req for req in self._approvals.values() if req.status == "PENDING"
        ]
        matching.sort(key=lambda r: (r.requested_at, r.id))
        return [copy.deepcopy(r) for r in matching]

    def add_decision(self, decision: ApprovalDecision) -> None:
        if decision.approval_id not in self._decisions:
            self._decisions[decision.approval_id] = []
        self._decisions[decision.approval_id].append(copy.deepcopy(decision))

    def list_decisions(self, approval_id: str) -> list[ApprovalDecision]:
        decisions = self._decisions.get(approval_id, [])
        return [copy.deepcopy(d) for d in decisions]
