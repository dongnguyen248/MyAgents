from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from asf.approval.errors import ApprovalError
from asf.approval.models import (
    ApprovalDecision,
    ApprovalFeedback,
    ApprovalPolicy,
    ApprovalRequest,
    ApprovalSpec,
)
from asf.approval.ports import ApprovalRepository

__all__ = ["ApprovalService"]


def _require_aware_datetime(dt: datetime, name: str = "now") -> None:
    if not isinstance(dt, datetime):
        raise TypeError(f"{name} must be a datetime instance")
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")


class ApprovalService:
    def __init__(
        self,
        repository: ApprovalRepository,
        *,
        id_factory: Callable[[], str],
    ) -> None:
        self._repository = repository
        self._id_factory = id_factory

    def request(
        self,
        spec: ApprovalSpec,
        policy: ApprovalPolicy,
        now: datetime,
    ) -> ApprovalRequest:
        _require_aware_datetime(now, "now")

        # At most one PENDING request per (taskId, artifactId, type)
        pending_requests = self._repository.list_pending()
        for req in pending_requests:
            if (
                req.task_id == spec.task_id
                and req.artifact_id == spec.artifact_id
                and req.type == spec.type
            ):
                raise ApprovalError(
                    "VALIDATION_FAILED",
                    f"A pending approval request already exists for task '{spec.task_id}', "
                    f"artifact '{spec.artifact_id}', and type '{spec.type}'",
                    details={
                        "taskId": spec.task_id,
                        "artifactId": spec.artifact_id,
                        "type": spec.type,
                    },
                )

        expires_at: datetime | None = None
        if policy.expires_in_seconds is not None:
            expires_at = now + timedelta(seconds=policy.expires_in_seconds)

        approval_id = self._id_factory()
        approval = ApprovalRequest(
            id=approval_id,
            task_id=spec.task_id,
            workflow_id=spec.workflow_id,
            project_id=spec.project_id,
            artifact_id=spec.artifact_id,
            type=spec.type,
            status="PENDING",
            requested_by=spec.requested_by,
            requested_at=now,
            expires_at=expires_at,
            min_approvals=policy.min_approvals,
            reviewers=list(policy.reviewers),
            metadata=dict(spec.metadata),
        )

        return self._repository.create(approval)

    def get(self, approval_id: str) -> ApprovalRequest:
        req = self._repository.get(approval_id)
        if req is None:
            raise ApprovalError(
                "NOT_FOUND",
                f"Approval request '{approval_id}' not found",
                details={"approvalId": approval_id},
            )
        return req

    def decide(self, decision: ApprovalDecision) -> ApprovalRequest:
        # Rule 1: unknown approvalId -> NOT_FOUND
        req = self._repository.get(decision.approval_id)
        if req is None:
            raise ApprovalError(
                "NOT_FOUND",
                f"Approval request '{decision.approval_id}' not found",
                details={"approvalId": decision.approval_id},
            )

        # Rule 2: closed-request rule (A6), including lazy expiry
        if req.status == "EXPIRED":
            raise ApprovalError(
                "APPROVAL_EXPIRED",
                f"Approval request '{req.id}' has expired",
                details={"approvalId": req.id, "status": "EXPIRED"},
            )
        if req.status in ("APPROVED", "REJECTED", "CHANGES_REQUESTED"):
            raise ApprovalError(
                "APPROVAL_ALREADY_DECIDED",
                f"Approval request '{req.id}' is already closed with status '{req.status}'",
                details={"approvalId": req.id, "status": req.status},
            )
        if req.status == "CANCELLED":
            raise ApprovalError(
                "VALIDATION_FAILED",
                f"Approval request '{req.id}' has been cancelled",
                details={"approvalId": req.id, "status": "CANCELLED"},
            )

        # Lazy expiry: status is PENDING and expiresAt is not null
        # and decision.createdAt >= expiresAt
        if (
            req.status == "PENDING"
            and req.expires_at is not None
            and decision.created_at >= req.expires_at
        ):
            expired_req = req.model_copy(update={"status": "EXPIRED"})
            self._repository.update(expired_req)
            raise ApprovalError(
                "APPROVAL_EXPIRED",
                f"Approval request '{req.id}' has expired",
                details={"approvalId": req.id, "status": "EXPIRED"},
            )

        # Rule 3: decision.createdAt earlier than requestedAt -> VALIDATION_FAILED
        if decision.created_at < req.requested_at:
            raise ApprovalError(
                "VALIDATION_FAILED",
                f"Decision createdAt ({decision.created_at.isoformat()}) cannot be earlier "
                f"than requestedAt ({req.requested_at.isoformat()})",
                details={
                    "approvalId": req.id,
                    "createdAt": decision.created_at.isoformat(),
                    "requestedAt": req.requested_at.isoformat(),
                },
            )

        # Rule 4: reviewer not in the request's reviewers -> APPROVAL_NOT_AUTHORIZED
        # (nothing stored)
        if decision.reviewer not in req.reviewers:
            raise ApprovalError(
                "APPROVAL_NOT_AUTHORIZED",
                f"Reviewer '{decision.reviewer}' is not authorized to decide approval '{req.id}'",
                details={"approvalId": req.id, "reviewer": decision.reviewer},
            )

        # Rule 5: decision REJECTED or REQUEST_CHANGES with an empty or whitespace-only
        # comment -> VALIDATION_FAILED
        if decision.decision in ("REJECTED", "REQUEST_CHANGES") and not decision.comment.strip():
            raise ApprovalError(
                "VALIDATION_FAILED",
                f"Comment is required for {decision.decision} decisions",
                details={"approvalId": req.id, "decision": decision.decision},
            )

        # Rule 6: decision APPROVED from a reviewer who already approved this request
        # -> APPROVAL_ALREADY_DECIDED
        if decision.decision == "APPROVED":
            prior_decisions = self._repository.list_decisions(req.id)
            approving_reviewers = {
                d.reviewer for d in prior_decisions if d.decision == "APPROVED"
            }
            if decision.reviewer in approving_reviewers:
                raise ApprovalError(
                    "APPROVAL_ALREADY_DECIDED",
                    f"Reviewer '{decision.reviewer}' has already approved request '{req.id}'",
                    details={"approvalId": req.id, "reviewer": decision.reviewer},
                )

        # Rule 7: otherwise store the decision
        self._repository.add_decision(decision)

        if decision.decision == "REJECTED":
            new_status = "REJECTED"
        elif decision.decision == "REQUEST_CHANGES":
            new_status = "CHANGES_REQUESTED"
        elif decision.decision == "APPROVED":
            all_decisions = self._repository.list_decisions(req.id)
            distinct_approvers = {
                d.reviewer for d in all_decisions if d.decision == "APPROVED"
            }
            if len(distinct_approvers) >= req.min_approvals:
                new_status = "APPROVED"
            else:
                new_status = "PENDING"
        else:
            new_status = req.status

        if new_status != req.status:
            updated_req = req.model_copy(update={"status": new_status})
            return self._repository.update(updated_req)
        return req

    def cancel(self, approval_id: str, now: datetime) -> ApprovalRequest:
        _require_aware_datetime(now, "now")

        req = self._repository.get(approval_id)
        if req is None:
            raise ApprovalError(
                "NOT_FOUND",
                f"Approval request '{approval_id}' not found",
                details={"approvalId": approval_id},
            )

        if req.status == "EXPIRED":
            raise ApprovalError(
                "APPROVAL_EXPIRED",
                f"Approval request '{req.id}' has expired",
                details={"approvalId": req.id, "status": "EXPIRED"},
            )
        if req.status in ("APPROVED", "REJECTED", "CHANGES_REQUESTED"):
            raise ApprovalError(
                "APPROVAL_ALREADY_DECIDED",
                f"Approval request '{req.id}' is already closed with status '{req.status}'",
                details={"approvalId": req.id, "status": req.status},
            )
        if req.status == "CANCELLED":
            raise ApprovalError(
                "VALIDATION_FAILED",
                f"Approval request '{req.id}' has already been cancelled",
                details={"approvalId": req.id, "status": "CANCELLED"},
            )

        cancelled_req = req.model_copy(update={"status": "CANCELLED"})
        return self._repository.update(cancelled_req)

    def expire_due(self, now: datetime) -> list[ApprovalRequest]:
        _require_aware_datetime(now, "now")

        pending = self._repository.list_pending()
        due = [
            r
            for r in pending
            if r.status == "PENDING"
            and r.expires_at is not None
            and r.expires_at <= now
        ]
        due.sort(key=lambda r: (r.expires_at, r.id))

        expired_list: list[ApprovalRequest] = []
        for r in due:
            expired_req = r.model_copy(update={"status": "EXPIRED"})
            updated = self._repository.update(expired_req)
            expired_list.append(updated)

        return expired_list

    def decisions(self, approval_id: str) -> list[ApprovalDecision]:
        req = self._repository.get(approval_id)
        if req is None:
            raise ApprovalError(
                "NOT_FOUND",
                f"Approval request '{approval_id}' not found",
                details={"approvalId": approval_id},
            )
        return self._repository.list_decisions(approval_id)

    def feedback_for(self, approval_id: str) -> list[ApprovalFeedback]:
        req = self._repository.get(approval_id)
        if req is None:
            raise ApprovalError(
                "NOT_FOUND",
                f"Approval request '{approval_id}' not found",
                details={"approvalId": approval_id},
            )
        all_decisions = self._repository.list_decisions(approval_id)
        feedback: list[ApprovalFeedback] = []
        for d in all_decisions:
            if d.decision in ("REJECTED", "REQUEST_CHANGES"):
                feedback.append(
                    ApprovalFeedback(
                        approval_id=d.approval_id,
                        reviewer=d.reviewer,
                        decision=d.decision,
                        comment=d.comment,
                    )
                )
        return feedback
