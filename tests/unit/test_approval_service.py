from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from asf.approval.errors import ERROR_CATEGORIES, ApprovalError
from asf.approval.models import (
    ApprovalDecision,
    ApprovalPolicy,
    ApprovalSpec,
)
from asf.approval.service import ApprovalService
from asf.storage.memory import InMemoryApprovalRepository

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "contracts" / "schemas" / "contracts.schema.json"
ERRORS_PATH = REPO_ROOT / "contracts" / "errors.md"

with SCHEMA_PATH.open(encoding="utf-8") as f:
    SCHEMA = json.load(f)

T0 = datetime(2026, 10, 20, 10, 0, 0, tzinfo=timezone.utc)
T1 = datetime(2026, 10, 20, 10, 15, 0, tzinfo=timezone.utc)
T2 = datetime(2026, 10, 20, 10, 30, 0, tzinfo=timezone.utc)
T3 = datetime(2026, 10, 20, 10, 45, 0, tzinfo=timezone.utc)
T_EXPIRE = datetime(2026, 10, 20, 11, 0, 0, tzinfo=timezone.utc)
T_BEFORE_EXPIRE = datetime(2026, 10, 20, 10, 59, 59, tzinfo=timezone.utc)
T_AFTER_EXPIRE = datetime(2026, 10, 20, 11, 0, 1, tzinfo=timezone.utc)
NAIVE_TIME = datetime(2026, 10, 20, 10, 0, 0)


def validator_for(definition: str) -> Draft202012Validator:
    wrapped = {
        "$schema": SCHEMA["$schema"],
        "$defs": SCHEMA["$defs"],
        "$ref": f"#/$defs/{definition}",
    }
    return Draft202012Validator(wrapped, format_checker=FormatChecker())


class CountingIdFactory:
    def __init__(self, prefix: str = "app-") -> None:
        self.count = 0
        self.prefix = prefix

    def __call__(self) -> str:
        self.count += 1
        return f"{self.prefix}{self.count}"


def default_spec(
    task_id: str = "task-1",
    artifact_id: str = "art-1",
    req_type: str = "SPEC",
) -> ApprovalSpec:
    return ApprovalSpec(
        task_id=task_id,
        workflow_id="software-development",
        project_id="sample",
        artifact_id=artifact_id,
        type=req_type,
        requested_by="orchestrator",
        metadata={"key": "val"},
    )


class ApprovalServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = InMemoryApprovalRepository()
        self.id_factory = CountingIdFactory()
        self.service = ApprovalService(self.repo, id_factory=self.id_factory)

    # (1) single reviewer happy path, request fields snapshot, expiresAt computed and null
    def test_single_reviewer_happy_path(self):
        policy = ApprovalPolicy(
            min_approvals=1,
            reviewers=["reviewer-1"],
            expires_in_seconds=3600,
        )
        spec = default_spec()
        req = self.service.request(spec, policy, T0)

        # Snapshot check
        self.assertEqual(req.id, "app-1")
        self.assertEqual(req.min_approvals, 1)
        self.assertEqual(req.reviewers, ["reviewer-1"])
        self.assertEqual(req.requested_at, T0)
        self.assertEqual(req.expires_at, T0 + timedelta(seconds=3600))
        self.assertEqual(req.status, "PENDING")
        self.assertEqual(req.metadata, {"key": "val"})

        # Decision
        decision = ApprovalDecision(
            approval_id=req.id,
            decision="APPROVED",
            reviewer="reviewer-1",
            comment="looks good",
            created_at=T1,
        )
        decided = self.service.decide(decision)
        self.assertEqual(decided.status, "APPROVED")
        self.assertEqual(self.service.get(req.id).status, "APPROVED")

        # Null expiry case
        policy_no_exp = ApprovalPolicy(min_approvals=1, reviewers=["reviewer-1"])
        req_no_exp = self.service.request(default_spec(artifact_id="art-2"), policy_no_exp, T0)
        self.assertIsNone(req_no_exp.expires_at)

    # (2) two reviewers with minApprovals 2: first APPROVED stays PENDING,
    # second distinct reviewer closes it, same reviewer twice -> APPROVAL_ALREADY_DECIDED
    def test_two_reviewers_min_approvals_two(self):
        policy = ApprovalPolicy(
            min_approvals=2,
            reviewers=["reviewer-1", "reviewer-2"],
        )
        req = self.service.request(default_spec(), policy, T0)

        # First approval keeps it PENDING
        d1 = ApprovalDecision(
            approval_id=req.id,
            decision="APPROVED",
            reviewer="reviewer-1",
            comment="LGTM 1",
            created_at=T1,
        )
        res1 = self.service.decide(d1)
        self.assertEqual(res1.status, "PENDING")

        # Same reviewer attempts second APPROVED -> APPROVAL_ALREADY_DECIDED
        d1_dup = ApprovalDecision(
            approval_id=req.id,
            decision="APPROVED",
            reviewer="reviewer-1",
            comment="LGTM again",
            created_at=T2,
        )
        with self.assertRaises(ApprovalError) as ctx:
            self.service.decide(d1_dup)
        self.assertEqual(ctx.exception.code, "APPROVAL_ALREADY_DECIDED")
        self.assertEqual(ctx.exception.details.get("reviewer"), "reviewer-1")

        # Second distinct reviewer approves -> closes to APPROVED
        d2 = ApprovalDecision(
            approval_id=req.id,
            decision="APPROVED",
            reviewer="reviewer-2",
            comment="LGTM 2",
            created_at=T2,
        )
        res2 = self.service.decide(d2)
        self.assertEqual(res2.status, "APPROVED")

    # (3) REJECTED and REQUEST_CHANGES close immediately and need a non-empty comment
    # (empty -> VALIDATION_FAILED)
    def test_rejected_and_request_changes_decisions(self):
        policy = ApprovalPolicy(min_approvals=2, reviewers=["r1", "r2"])

        # Empty or whitespace comment on REJECTED
        req1 = self.service.request(default_spec(artifact_id="art-1"), policy, T0)
        d_empty_rej = ApprovalDecision(
            approval_id=req1.id,
            decision="REJECTED",
            reviewer="r1",
            comment="   ",
            created_at=T1,
        )
        with self.assertRaises(ApprovalError) as ctx:
            self.service.decide(d_empty_rej)
        self.assertEqual(ctx.exception.code, "VALIDATION_FAILED")
        self.assertEqual(self.service.get(req1.id).status, "PENDING")

        # Valid comment on REJECTED -> closes immediately
        d_ok_rej = ApprovalDecision(
            approval_id=req1.id,
            decision="REJECTED",
            reviewer="r1",
            comment="Cannot proceed with this plan",
            created_at=T1,
        )
        res_rej = self.service.decide(d_ok_rej)
        self.assertEqual(res_rej.status, "REJECTED")

        # Empty comment on REQUEST_CHANGES
        req2 = self.service.request(default_spec(artifact_id="art-2"), policy, T0)
        d_empty_changes = ApprovalDecision(
            approval_id=req2.id,
            decision="REQUEST_CHANGES",
            reviewer="r2",
            comment="",
            created_at=T1,
        )
        with self.assertRaises(ApprovalError) as ctx:
            self.service.decide(d_empty_changes)
        self.assertEqual(ctx.exception.code, "VALIDATION_FAILED")

        # Valid comment on REQUEST_CHANGES -> closes immediately
        d_ok_changes = ApprovalDecision(
            approval_id=req2.id,
            decision="REQUEST_CHANGES",
            reviewer="r2",
            comment="Please add more details",
            created_at=T1,
        )
        res_changes = self.service.decide(d_ok_changes)
        self.assertEqual(res_changes.status, "CHANGES_REQUESTED")

    # (4) unauthorized reviewer -> APPROVAL_NOT_AUTHORIZED and nothing stored
    def test_unauthorized_reviewer(self):
        policy = ApprovalPolicy(min_approvals=1, reviewers=["reviewer-1"])
        req = self.service.request(default_spec(), policy, T0)

        decision = ApprovalDecision(
            approval_id=req.id,
            decision="APPROVED",
            reviewer="intruder",
            comment="I approve",
            created_at=T1,
        )
        with self.assertRaises(ApprovalError) as ctx:
            self.service.decide(decision)
        self.assertEqual(ctx.exception.code, "APPROVAL_NOT_AUTHORIZED")
        self.assertEqual(ctx.exception.details.get("reviewer"), "intruder")

        # Verify nothing was stored
        self.assertEqual(self.service.decisions(req.id), [])
        self.assertEqual(self.service.get(req.id).status, "PENDING")

    # (5) unknown id -> NOT_FOUND for get, decide, cancel, feedback_for
    def test_unknown_id_returns_not_found(self):
        with self.assertRaises(ApprovalError) as ctx:
            self.service.get("unknown-id")
        self.assertEqual(ctx.exception.code, "NOT_FOUND")

        with self.assertRaises(ApprovalError) as ctx:
            self.service.decide(
                ApprovalDecision(
                    approval_id="unknown-id",
                    decision="APPROVED",
                    reviewer="r1",
                    comment="ok",
                    created_at=T1,
                )
            )
        self.assertEqual(ctx.exception.code, "NOT_FOUND")

        with self.assertRaises(ApprovalError) as ctx:
            self.service.cancel("unknown-id", T1)
        self.assertEqual(ctx.exception.code, "NOT_FOUND")

        with self.assertRaises(ApprovalError) as ctx:
            self.service.feedback_for("unknown-id")
        self.assertEqual(ctx.exception.code, "NOT_FOUND")

    # (6) decision at exactly expiresAt -> APPROVAL_EXPIRED and the stored status becomes EXPIRED,
    # one second earlier is accepted
    def test_lazy_expiry_at_expires_at(self):
        policy = ApprovalPolicy(
            min_approvals=1,
            reviewers=["r1"],
            expires_in_seconds=3600,
        )
        # Request 1: decision 1 second earlier than expiresAt is accepted
        req1 = self.service.request(default_spec(artifact_id="art-1"), policy, T0)
        d_early = ApprovalDecision(
            approval_id=req1.id,
            decision="APPROVED",
            reviewer="r1",
            comment="ok",
            created_at=T_BEFORE_EXPIRE,
        )
        res1 = self.service.decide(d_early)
        self.assertEqual(res1.status, "APPROVED")

        # Request 2: decision exactly at expiresAt -> APPROVAL_EXPIRED and persists EXPIRED
        req2 = self.service.request(default_spec(artifact_id="art-2"), policy, T0)
        d_at_exp = ApprovalDecision(
            approval_id=req2.id,
            decision="APPROVED",
            reviewer="r1",
            comment="ok",
            created_at=T_EXPIRE,
        )
        with self.assertRaises(ApprovalError) as ctx:
            self.service.decide(d_at_exp)
        self.assertEqual(ctx.exception.code, "APPROVAL_EXPIRED")
        self.assertEqual(self.service.get(req2.id).status, "EXPIRED")

    # (7) decision earlier than requestedAt -> VALIDATION_FAILED
    def test_decision_earlier_than_requested_at(self):
        policy = ApprovalPolicy(min_approvals=1, reviewers=["r1"])
        req = self.service.request(default_spec(), policy, T1)

        d_early = ApprovalDecision(
            approval_id=req.id,
            decision="APPROVED",
            reviewer="r1",
            comment="ok",
            created_at=T0,  # earlier than requestedAt T1
        )
        with self.assertRaises(ApprovalError) as ctx:
            self.service.decide(d_early)
        self.assertEqual(ctx.exception.code, "VALIDATION_FAILED")
        self.assertEqual(self.service.get(req.id).status, "PENDING")

    # (8) expire_due: only due PENDING requests, ordering, idempotent second call []
    def test_expire_due(self):
        # expires T2
        p1 = ApprovalPolicy(min_approvals=1, reviewers=["r1"], expires_in_seconds=1800)
        # expires T1
        p2 = ApprovalPolicy(min_approvals=1, reviewers=["r1"], expires_in_seconds=900)
        # no expiry
        p3 = ApprovalPolicy(min_approvals=1, reviewers=["r1"])

        r_t2 = self.service.request(default_spec(artifact_id="a-t2"), p1, T0)
        r_t1_b = self.service.request(default_spec(artifact_id="a-t1-b"), p2, T0)
        r_t1_a = self.service.request(default_spec(artifact_id="a-t1-a"), p2, T0)
        r_none = self.service.request(default_spec(artifact_id="a-none"), p3, T0)

        # expire_due at T1: r_t1_b and r_t1_a are due
        expired_at_t1 = self.service.expire_due(T1)
        self.assertEqual([r.id for r in expired_at_t1], [r_t1_b.id, r_t1_a.id])
        self.assertTrue(all(r.status == "EXPIRED" for r in expired_at_t1))

        # Idempotent second call returns []
        self.assertEqual(self.service.expire_due(T1), [])

        # Non-due requests are still PENDING
        self.assertEqual(self.service.get(r_t2.id).status, "PENDING")
        self.assertEqual(self.service.get(r_none.id).status, "PENDING")

        # expire_due at T2: now r_t2 expires
        expired_at_t2 = self.service.expire_due(T2)
        self.assertEqual([r.id for r in expired_at_t2], [r_t2.id])
        self.assertEqual(self.service.get(r_none.id).status, "PENDING")

    # (9) cancel: PENDING -> CANCELLED; cancel or decide on closed requests (matrix test for A6)
    def test_cancel_and_decide_closed_request_matrix(self):
        policy = ApprovalPolicy(min_approvals=1, reviewers=["r1"])

        # PENDING -> CANCELLED
        req = self.service.request(default_spec(), policy, T0)
        cancelled = self.service.cancel(req.id, T1)
        self.assertEqual(cancelled.status, "CANCELLED")

        # Matrix of states and expected errors
        matrix_cases = [
            ("EXPIRED", "APPROVAL_EXPIRED", "APPROVAL_EXPIRED"),
            ("APPROVED", "APPROVAL_ALREADY_DECIDED", "APPROVAL_ALREADY_DECIDED"),
            ("REJECTED", "APPROVAL_ALREADY_DECIDED", "APPROVAL_ALREADY_DECIDED"),
            ("CHANGES_REQUESTED", "APPROVAL_ALREADY_DECIDED", "APPROVAL_ALREADY_DECIDED"),
            ("CANCELLED", "VALIDATION_FAILED", "VALIDATION_FAILED"),
        ]

        for initial_status, expected_decide_err, expected_cancel_err in matrix_cases:
            with self.subTest(status=initial_status):
                r = self.service.request(
                    default_spec(artifact_id=f"art-{initial_status}"),
                    policy,
                    T0,
                )
                # Force status directly in repo
                updated = r.model_copy(update={"status": initial_status})
                self.repo.update(updated)

                # Test decide
                d = ApprovalDecision(
                    approval_id=r.id,
                    decision="APPROVED",
                    reviewer="r1",
                    comment="ok",
                    created_at=T1,
                )
                with self.assertRaises(ApprovalError) as ctx_decide:
                    self.service.decide(d)
                self.assertEqual(ctx_decide.exception.code, expected_decide_err)
                if initial_status == "CANCELLED":
                    self.assertEqual(ctx_decide.exception.details.get("status"), "CANCELLED")

                # Test cancel
                with self.assertRaises(ApprovalError) as ctx_cancel:
                    self.service.cancel(r.id, T1)
                self.assertEqual(ctx_cancel.exception.code, expected_cancel_err)
                if initial_status == "CANCELLED":
                    self.assertEqual(ctx_cancel.exception.details.get("status"), "CANCELLED")

    # (10) a second PENDING request for the same (task, artifact, type) -> VALIDATION_FAILED,
    # a new one after closing is allowed
    def test_second_pending_request_constraint(self):
        policy = ApprovalPolicy(min_approvals=1, reviewers=["r1"])
        spec = default_spec(task_id="t1", artifact_id="art1", req_type="SPEC")

        # First request succeeds
        req1 = self.service.request(spec, policy, T0)

        # Duplicate pending request fails
        with self.assertRaises(ApprovalError) as ctx:
            self.service.request(spec, policy, T0)
        self.assertEqual(ctx.exception.code, "VALIDATION_FAILED")

        # Different artifact or type succeeds
        spec_diff_art = default_spec(task_id="t1", artifact_id="art2", req_type="SPEC")
        self.service.request(spec_diff_art, policy, T0)

        spec_diff_type = default_spec(task_id="t1", artifact_id="art1", req_type="PLAN")
        self.service.request(spec_diff_type, policy, T0)

        # Close first request
        self.service.cancel(req1.id, T1)

        # Now a new pending request for the same (t1, art1, SPEC) is allowed
        req2 = self.service.request(spec, policy, T2)
        self.assertEqual(req2.status, "PENDING")

    def test_pending_request_expiry_blocking_cases(self):
        # Case 1: Overdue PENDING request (expiresAt <= now) does NOT block;
        # request() does not modify it
        policy_exp = ApprovalPolicy(min_approvals=1, reviewers=["r1"], expires_in_seconds=60)
        spec = default_spec(task_id="t_overdue", artifact_id="art_overdue", req_type="SPEC")
        req1 = self.service.request(spec, policy_exp, T0)
        # At T0 + 120s, req1 is overdue (expires_at is T0 + 60s <= T0 + 120s)
        t_overdue = T0 + timedelta(seconds=120)
        # Should NOT block:
        req2 = self.service.request(spec, policy_exp, t_overdue)
        self.assertEqual(req2.status, "PENDING")
        self.assertNotEqual(req1.id, req2.id)
        # request() did NOT modify req1 (still PENDING):
        stored_req1 = self.service.get(req1.id)
        self.assertEqual(stored_req1.status, "PENDING")

        # Case 2: PENDING request without expiry (expiresAt is None) STILL blocks
        policy_no_exp = ApprovalPolicy(min_approvals=1, reviewers=["r1"], expires_in_seconds=None)
        spec_no_exp = default_spec(task_id="t_no_exp", artifact_id="art_no_exp", req_type="SPEC")
        self.service.request(spec_no_exp, policy_no_exp, T0)
        with self.assertRaises(ApprovalError) as ctx:
            self.service.request(spec_no_exp, policy_no_exp, t_overdue)
        self.assertEqual(ctx.exception.code, "VALIDATION_FAILED")

        # Case 3: PENDING request with future expiry (expiresAt > now) STILL blocks
        policy_future = ApprovalPolicy(min_approvals=1, reviewers=["r1"], expires_in_seconds=3600)
        spec_future = default_spec(task_id="t_future", artifact_id="art_future", req_type="SPEC")
        self.service.request(spec_future, policy_future, T0)
        t_before = T0 + timedelta(seconds=600)
        with self.assertRaises(ApprovalError) as ctx:
            self.service.request(spec_future, policy_future, t_before)
        self.assertEqual(ctx.exception.code, "VALIDATION_FAILED")

    def test_overdue_pending_request_cancel_and_no_lazy_expiry_on_read(self):
        policy = ApprovalPolicy(min_approvals=1, reviewers=["r1"], expires_in_seconds=60)
        spec = default_spec(
            task_id="t_cancel_overdue", artifact_id="art_cancel_overdue", req_type="SPEC"
        )
        req = self.service.request(spec, policy, T0)
        t_overdue = T0 + timedelta(seconds=120)

        # get() and decisions() never apply lazy expiry
        # (an overdue request stays PENDING until expire_due)
        fetched = self.service.get(req.id)
        self.assertEqual(fetched.status, "PENDING")
        decs = self.service.decisions(req.id)
        self.assertEqual(decs, [])
        fetched_after = self.service.get(req.id)
        self.assertEqual(fetched_after.status, "PENDING")

        # cancel() succeeds on an overdue PENDING request (result CANCELLED)
        cancelled = self.service.cancel(req.id, t_overdue)
        self.assertEqual(cancelled.status, "CANCELLED")
        self.assertEqual(self.service.get(req.id).status, "CANCELLED")

    # (11) feedback_for returns only negative decisions in order, [] when none,
    # each item validates against $defs/ApprovalFeedback, and an AgentRequest dict
    # carrying that list validates against $defs/AgentRequest
    def test_feedback_for_negative_decisions(self):
        policy = ApprovalPolicy(min_approvals=2, reviewers=["r1", "r2"])
        req = self.service.request(default_spec(), policy, T0)

        # Empty feedback when no decisions
        self.assertEqual(self.service.feedback_for(req.id), [])

        # Add decisions: APPROVED, REQUEST_CHANGES, REJECTED
        d_app = ApprovalDecision(
            approval_id=req.id,
            decision="APPROVED",
            reviewer="r1",
            comment="ok",
            created_at=T1,
        )
        self.service.decide(d_app)

        # Force add extra decisions to repo to simulate multiple reviewer feedback rounds
        d_changes = ApprovalDecision(
            approval_id=req.id,
            decision="REQUEST_CHANGES",
            reviewer="r2",
            comment="Fix line 42",
            created_at=T2,
        )
        self.repo.add_decision(d_changes)

        d_rej = ApprovalDecision(
            approval_id=req.id,
            decision="REJECTED",
            reviewer="r1",
            comment="Architecture flaw",
            created_at=T3,
        )
        self.repo.add_decision(d_rej)

        feedbacks = self.service.feedback_for(req.id)
        self.assertEqual(len(feedbacks), 2)
        self.assertEqual(feedbacks[0].decision, "REQUEST_CHANGES")
        self.assertEqual(feedbacks[0].comment, "Fix line 42")
        self.assertEqual(feedbacks[1].decision, "REJECTED")
        self.assertEqual(feedbacks[1].comment, "Architecture flaw")

        # Validate against $defs/ApprovalFeedback
        for fb in feedbacks:
            validator_for("ApprovalFeedback").validate(fb.to_contract())

        # Validate AgentRequest carrying feedback list
        agent_req_dict = {
            "requestId": "req-1",
            "taskId": "task-1",
            "projectId": "sample",
            "workflowId": "software-development",
            "agentId": "spec",
            "input": {"task": "do work"},
            "context": {},
            "artifacts": [],
            "feedback": [fb.to_contract() for fb in feedbacks],
            "metadata": {},
        }
        validator_for("AgentRequest").validate(agent_req_dict)

    # (12) every ApprovalError.to_platform_error validates against $defs/PlatformError,
    # categories equal the contracts/errors.md table for these codes, naive now -> ValueError
    def test_approval_error_to_platform_error_and_catalog(self):
        # Parse contracts/errors.md
        table_cats: dict[str, str] = {}
        for line in ERRORS_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line.startswith("|") or line.startswith("|---"):
                continue
            parts = [p.strip() for p in line.strip("|").split("|")]
            if len(parts) >= 2 and parts[0] != "code":
                table_cats[parts[0]] = parts[1]

        error_codes = [
            "NOT_FOUND",
            "VALIDATION_FAILED",
            "APPROVAL_EXPIRED",
            "APPROVAL_ALREADY_DECIDED",
            "APPROVAL_NOT_AUTHORIZED",
        ]

        for code in error_codes:
            with self.subTest(code=code):
                err = ApprovalError(code, f"Error message for {code}", details={"foo": "bar"})
                # Category matches errors.md table
                self.assertEqual(ERROR_CATEGORIES[code], table_cats[code])

                # Valid aware timestamp produces valid PlatformError
                pe = err.to_platform_error(T0)
                validator_for("PlatformError").validate(pe)
                self.assertEqual(pe["code"], code)
                self.assertEqual(pe["category"], table_cats[code])
                self.assertFalse(pe["retryable"])
                self.assertEqual(pe["details"], {"foo": "bar"})

                # Naive now raises ValueError
                with self.assertRaises(ValueError):
                    err.to_platform_error(NAIVE_TIME)

    # (13) all `now` arguments naive -> ValueError
    def test_naive_now_arguments_rejected(self):
        policy = ApprovalPolicy(min_approvals=1, reviewers=["r1"])
        spec = default_spec()

        # request
        with self.assertRaises(ValueError):
            self.service.request(spec, policy, NAIVE_TIME)

        req = self.service.request(spec, policy, T0)

        # cancel
        with self.assertRaises(ValueError):
            self.service.cancel(req.id, NAIVE_TIME)

        # expire_due
        with self.assertRaises(ValueError):
            self.service.expire_due(NAIVE_TIME)

    # (14) failed operations leave the repository unchanged (except the lazy EXPIRED in 6)
    def test_failed_operations_leave_repository_unchanged(self):
        policy = ApprovalPolicy(min_approvals=1, reviewers=["r1"])
        req = self.service.request(default_spec(), policy, T0)

        # 1. Unauthorized reviewer
        bad_rev = ApprovalDecision(
            approval_id=req.id, decision="APPROVED", reviewer="bad", comment="ok", created_at=T1
        )
        with self.assertRaises(ApprovalError):
            self.service.decide(bad_rev)
        self.assertEqual(self.service.decisions(req.id), [])
        self.assertEqual(self.service.get(req.id).status, "PENDING")

        # 2. Empty comment on REJECTED
        empty_com = ApprovalDecision(
            approval_id=req.id, decision="REJECTED", reviewer="r1", comment="", created_at=T1
        )
        with self.assertRaises(ApprovalError):
            self.service.decide(empty_com)
        self.assertEqual(self.service.decisions(req.id), [])
        self.assertEqual(self.service.get(req.id).status, "PENDING")

        # 3. Decision earlier than requestedAt
        early_d = ApprovalDecision(
            approval_id=req.id,
            decision="APPROVED",
            reviewer="r1",
            comment="ok",
            created_at=T0 - timedelta(seconds=10),
        )
        with self.assertRaises(ApprovalError):
            self.service.decide(early_d)
        self.assertEqual(self.service.decisions(req.id), [])
        self.assertEqual(self.service.get(req.id).status, "PENDING")

        # 4. Duplicate approver
        policy_multi = ApprovalPolicy(min_approvals=2, reviewers=["r1", "r2"])
        req_multi = self.service.request(default_spec(artifact_id="art-multi"), policy_multi, T0)
        d_first = ApprovalDecision(
            approval_id=req_multi.id,
            decision="APPROVED",
            reviewer="r1",
            comment="ok",
            created_at=T1,
        )
        self.service.decide(d_first)
        self.assertEqual(len(self.service.decisions(req_multi.id)), 1)
        self.assertEqual(self.service.get(req_multi.id).status, "PENDING")

        d_dup = ApprovalDecision(
            approval_id=req_multi.id,
            decision="APPROVED",
            reviewer="r1",
            comment="ok again",
            created_at=T2,
        )
        with self.assertRaises(ApprovalError):
            self.service.decide(d_dup)
        self.assertEqual(len(self.service.decisions(req_multi.id)), 1)
        self.assertEqual(self.service.get(req_multi.id).status, "PENDING")

    # (15) aliasing: mutating inputs or returned objects does not change stored request
    def test_aliasing_and_isolation_at_service_boundary(self):
        metadata_dict = {"env": "prod", "nested": {"key": "val"}}
        spec = ApprovalSpec(
            task_id="task-1",
            workflow_id="software-development",
            project_id="sample",
            artifact_id="art-1",
            type="SPEC",
            requested_by="orchestrator",
            metadata=metadata_dict,
        )
        reviewers_list = ["r1", "r2"]
        policy = ApprovalPolicy(min_approvals=1, reviewers=reviewers_list)

        req = self.service.request(spec, policy, T0)

        # 1. Mutating caller's metadata dict after request() does not affect stored request
        metadata_dict["env"] = "mutated"
        metadata_dict["nested"]["key"] = "mutated"
        spec.metadata["env"] = "mutated_spec"
        stored = self.service.get(req.id)
        self.assertEqual(stored.metadata, {"env": "prod", "nested": {"key": "val"}})

        # 2. Mutating caller's reviewers list after request() does not affect stored request
        reviewers_list.append("r3")
        policy.reviewers.append("r4")
        stored = self.service.get(req.id)
        self.assertEqual(stored.reviewers, ["r1", "r2"])

        # 3. Mutating returned ApprovalRequest's metadata does not affect stored request
        req.metadata["env"] = "mutated_returned"
        req.metadata["nested"]["key"] = "mutated_returned"
        stored = self.service.get(req.id)
        self.assertEqual(stored.metadata, {"env": "prod", "nested": {"key": "val"}})

        # 4. Mutating returned ApprovalRequest's reviewers does not affect stored request
        req.reviewers.append("r5")
        stored = self.service.get(req.id)
        self.assertEqual(stored.reviewers, ["r1", "r2"])
