from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import get_args

from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from asf.approval.models import (
    ApprovalDecision,
    ApprovalFeedback,
    ApprovalPolicy,
    ApprovalRequest,
    ApprovalSpec,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "contracts" / "schemas" / "contracts.schema.json"
with SCHEMA_PATH.open(encoding="utf-8") as schema_file:
    SCHEMA = json.load(schema_file)

VALID_AWARE_TIME = datetime(2026, 10, 20, 14, 0, 0, tzinfo=timezone.utc)
NAIVE_TIME = datetime(2026, 10, 20, 14, 0, 0)


def validator_for(definition: str) -> Draft202012Validator:
    wrapped = {
        "$schema": SCHEMA["$schema"],
        "$defs": SCHEMA["$defs"],
        "$ref": f"#/$defs/{definition}",
    }
    return Draft202012Validator(wrapped, format_checker=FormatChecker())


class ApprovalModelsTests(unittest.TestCase):
    def test_to_contract_validates_against_defs_for_all_contract_models(self):
        policy = ApprovalPolicy(
            min_approvals=1,
            reviewers=["reviewer-1"],
            expires_in_seconds=3600,
        )
        validator_for("ApprovalPolicy").validate(policy.to_contract())

        request = ApprovalRequest(
            id="approval-1",
            task_id="task-1",
            workflow_id="software-development",
            project_id="sample",
            artifact_id="artifact-1",
            type="SPEC",
            status="PENDING",
            requested_by="orchestrator",
            requested_at=VALID_AWARE_TIME,
            expires_at=None,
            min_approvals=1,
            reviewers=["reviewer-1"],
            metadata={},
        )
        validator_for("ApprovalRequest").validate(request.to_contract())

        decision = ApprovalDecision(
            approval_id="approval-1",
            decision="APPROVED",
            reviewer="reviewer-1",
            comment="Looks good",
            created_at=VALID_AWARE_TIME,
        )
        validator_for("ApprovalDecision").validate(decision.to_contract())

        feedback = ApprovalFeedback(
            approval_id="approval-1",
            reviewer="reviewer-1",
            decision="REQUEST_CHANGES",
            comment="Please update requirements",
        )
        validator_for("ApprovalFeedback").validate(feedback.to_contract())

    def test_drift_guard_properties_and_literal_enums(self):
        models = [
            (
                "ApprovalPolicy",
                ApprovalPolicy(min_approvals=1, reviewers=["r1"], expires_in_seconds=100),
            ),
            (
                "ApprovalRequest",
                ApprovalRequest(
                    id="a1",
                    task_id="t1",
                    workflow_id="w1",
                    project_id="p1",
                    artifact_id="art1",
                    type="SPEC",
                    status="PENDING",
                    requested_by="orch",
                    requested_at=VALID_AWARE_TIME,
                    expires_at=VALID_AWARE_TIME,
                    min_approvals=1,
                    reviewers=["r1"],
                    metadata={},
                ),
            ),
            (
                "ApprovalDecision",
                ApprovalDecision(
                    approval_id="a1",
                    decision="APPROVED",
                    reviewer="r1",
                    comment="ok",
                    created_at=VALID_AWARE_TIME,
                ),
            ),
            (
                "ApprovalFeedback",
                ApprovalFeedback(
                    approval_id="a1",
                    reviewer="r1",
                    decision="REJECTED",
                    comment="reason",
                ),
            ),
        ]

        for def_name, instance in models:
            with self.subTest(contract=def_name):
                schema_props = set(SCHEMA["$defs"][def_name]["properties"].keys())
                model_keys = set(instance.to_contract().keys())
                self.assertEqual(
                    model_keys,
                    schema_props,
                    f"Drift in property names for {def_name}",
                )

        # Enums drift check
        request_status_field = ApprovalRequest.model_fields["status"]
        self.assertEqual(
            set(get_args(request_status_field.annotation)),
            set(SCHEMA["$defs"]["ApprovalRequest"]["properties"]["status"]["enum"]),
        )

        decision_field = ApprovalDecision.model_fields["decision"]
        self.assertEqual(
            set(get_args(decision_field.annotation)),
            set(SCHEMA["$defs"]["ApprovalDecision"]["properties"]["decision"]["enum"]),
        )

        feedback_decision_field = ApprovalFeedback.model_fields["decision"]
        self.assertEqual(
            set(get_args(feedback_decision_field.annotation)),
            set(SCHEMA["$defs"]["ApprovalFeedback"]["properties"]["decision"]["enum"]),
        )

    def test_naive_datetime_rejected(self):
        with self.assertRaises(ValidationError):
            ApprovalRequest(
                id="a1",
                task_id="t1",
                workflow_id="w1",
                project_id="p1",
                artifact_id="art1",
                type="SPEC",
                status="PENDING",
                requested_by="orch",
                requested_at=NAIVE_TIME,
                expires_at=None,
                min_approvals=1,
                reviewers=["r1"],
            )

        with self.assertRaises(ValidationError):
            ApprovalRequest(
                id="a1",
                task_id="t1",
                workflow_id="w1",
                project_id="p1",
                artifact_id="art1",
                type="SPEC",
                status="PENDING",
                requested_by="orch",
                requested_at=VALID_AWARE_TIME,
                expires_at=NAIVE_TIME,
                min_approvals=1,
                reviewers=["r1"],
            )

        with self.assertRaises(ValidationError):
            ApprovalDecision(
                approval_id="a1",
                decision="APPROVED",
                reviewer="r1",
                comment="ok",
                created_at=NAIVE_TIME,
            )

    def test_unknown_key_rejected(self):
        with self.assertRaises(ValidationError):
            ApprovalPolicy(min_approvals=1, reviewers=["r1"], extra_key="bad")  # type: ignore[call-arg]

        with self.assertRaises(ValidationError):
            ApprovalRequest(  # type: ignore[call-arg]
                id="a1",
                task_id="t1",
                workflow_id="w1",
                project_id="p1",
                artifact_id="art1",
                type="SPEC",
                status="PENDING",
                requested_by="orch",
                requested_at=VALID_AWARE_TIME,
                min_approvals=1,
                reviewers=["r1"],
                extra_key="bad",
            )

        with self.assertRaises(ValidationError):
            ApprovalDecision(  # type: ignore[call-arg]
                approval_id="a1",
                decision="APPROVED",
                reviewer="r1",
                created_at=VALID_AWARE_TIME,
                extra_key="bad",
            )

        with self.assertRaises(ValidationError):
            ApprovalFeedback(  # type: ignore[call-arg]
                approval_id="a1",
                reviewer="r1",
                decision="REJECTED",
                comment="no",
                extra_key="bad",
            )

    def test_policy_invariants(self):
        # min_approvals > len(reviewers)
        with self.assertRaises(ValidationError):
            ApprovalPolicy(min_approvals=3, reviewers=["r1", "r2"])

        # duplicate reviewers
        with self.assertRaises(ValidationError):
            ApprovalPolicy(min_approvals=1, reviewers=["r1", "r1"])

        # empty reviewer string
        with self.assertRaises(ValidationError):
            ApprovalPolicy(min_approvals=1, reviewers=[""])

        # empty reviewers list
        with self.assertRaises(ValidationError):
            ApprovalPolicy(min_approvals=1, reviewers=[])

    def test_reviewer_identifiers_accepted(self):
        valid_reviewers = ["8:orgid:abc", "user@example.com", "Jane Doe"]
        policy = ApprovalPolicy(min_approvals=1, reviewers=valid_reviewers)
        self.assertEqual(policy.reviewers, valid_reviewers)

        req = ApprovalRequest(
            id="a1",
            task_id="t1",
            workflow_id="w1",
            project_id="p1",
            artifact_id="art1",
            type="SPEC",
            status="PENDING",
            requested_by="orch",
            requested_at=VALID_AWARE_TIME,
            min_approvals=1,
            reviewers=valid_reviewers,
        )
        self.assertEqual(req.reviewers, valid_reviewers)

    def test_reviewer_identifier_whitespace_rejected(self):
        from asf.approval.models import INVALID_REVIEWER_MESSAGE

        bad_reviewers = ["", "   ", " a", "a ", " reviewer-1", "reviewer-1 ", "\tr1", "r1\n"]
        for bad in bad_reviewers:
            with self.subTest(bad=bad):
                with self.assertRaises(ValidationError) as ctx_policy:
                    ApprovalPolicy(min_approvals=1, reviewers=[bad])
                self.assertIn(
                    INVALID_REVIEWER_MESSAGE,
                    str(ctx_policy.exception),
                )

                with self.assertRaises(ValidationError) as ctx_req:
                    ApprovalRequest(
                        id="a1",
                        task_id="t1",
                        workflow_id="w1",
                        project_id="p1",
                        artifact_id="art1",
                        type="SPEC",
                        status="PENDING",
                        requested_by="orch",
                        requested_at=VALID_AWARE_TIME,
                        min_approvals=1,
                        reviewers=[bad],
                    )
                self.assertIn(
                    INVALID_REVIEWER_MESSAGE,
                    str(ctx_req.exception),
                )


        # same invariants for ApprovalRequest
        with self.assertRaises(ValidationError):
            ApprovalRequest(
                id="a1",
                task_id="t1",
                workflow_id="w1",
                project_id="p1",
                artifact_id="art1",
                type="SPEC",
                status="PENDING",
                requested_by="orch",
                requested_at=VALID_AWARE_TIME,
                min_approvals=3,
                reviewers=["r1", "r2"],
            )

        with self.assertRaises(ValidationError):
            ApprovalRequest(
                id="a1",
                task_id="t1",
                workflow_id="w1",
                project_id="p1",
                artifact_id="art1",
                type="SPEC",
                status="PENDING",
                requested_by="orch",
                requested_at=VALID_AWARE_TIME,
                min_approvals=1,
                reviewers=["r1", "r1"],
            )

    def test_policy_defaults(self):
        policy = ApprovalPolicy(reviewers=["reviewer-1"])
        self.assertEqual(policy.min_approvals, 1)
        self.assertIsNone(policy.expires_in_seconds)

    def test_models_do_not_mutate_inputs(self):
        reviewers = ["r1", "r2"]
        policy = ApprovalPolicy(min_approvals=2, reviewers=reviewers)
        reviewers.append("r3")
        self.assertEqual(policy.reviewers, ["r1", "r2"])

        spec = ApprovalSpec(
            task_id="t1",
            workflow_id="w1",
            project_id="p1",
            artifact_id="art1",
            type="SPEC",
            requested_by="orch",
            metadata={"key": "val"},
        )
        self.assertEqual(spec.metadata["key"], "val")
