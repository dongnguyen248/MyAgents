from __future__ import annotations

import unittest
from typing import Any

from asf.approval.policy import approval_policy_from_project
from asf.configuration.errors import ConfigError
from asf.configuration.project import ProjectProfile


def make_profile(config: dict[str, Any]) -> ProjectProfile:
    return ProjectProfile(
        id="sample",
        name="Sample Project",
        repository={"provider": "git"},
        technology={"backend": ["python"]},
        workflow="software-development",
        configuration=config,
    )


class ApprovalPolicyTests(unittest.TestCase):
    def test_valid_config_and_defaults(self):
        # Default minApprovals=1, expiresInSeconds=None
        profile = make_profile({"approval": {"reviewers": ["reviewer-1"]}})
        policy = approval_policy_from_project(profile)
        self.assertEqual(policy.min_approvals, 1)
        self.assertEqual(policy.reviewers, ["reviewer-1"])
        self.assertIsNone(policy.expires_in_seconds)

        # Explicit minApprovals and expiresInSeconds
        profile2 = make_profile({
            "approval": {
                "reviewers": ["r1", "r2"],
                "minApprovals": 2,
                "expiresInSeconds": 3600,
            }
        })
        policy2 = approval_policy_from_project(profile2)
        self.assertEqual(policy2.min_approvals, 2)
        self.assertEqual(policy2.reviewers, ["r1", "r2"])
        self.assertEqual(policy2.expires_in_seconds, 3600)

    def test_extra_and_channel_keys_ignored(self):
        profile = make_profile({
            "approval": {
                "reviewers": ["r1"],
                "channel": {"type": "teams", "target": "chan-1"},
                "extraField": "ignored",
            }
        })
        policy = approval_policy_from_project(profile)
        self.assertEqual(policy.reviewers, ["r1"])

    def assert_has_issue_path(self, error: ConfigError, expected_path: str) -> None:
        self.assertTrue(
            any(iss.path == expected_path for iss in error.issues),
            f"Expected issue path '{expected_path}' in {[i.path for i in error.issues]}",
        )

    def test_missing_approval_mapping(self):
        # Missing "approval" entirely
        with self.assertRaises(ConfigError) as ctx:
            approval_policy_from_project(make_profile({}))
        self.assert_has_issue_path(ctx.exception, "configuration.approval")

        # "approval" is not a mapping
        with self.assertRaises(ConfigError) as ctx:
            approval_policy_from_project(make_profile({"approval": "invalid"}))
        self.assert_has_issue_path(ctx.exception, "configuration.approval")

    def test_reviewers_validation(self):
        # Missing reviewers
        with self.assertRaises(ConfigError) as ctx:
            approval_policy_from_project(make_profile({"approval": {}}))
        self.assert_has_issue_path(ctx.exception, "configuration.approval.reviewers")

        # Empty reviewers list
        with self.assertRaises(ConfigError) as ctx:
            approval_policy_from_project(make_profile({"approval": {"reviewers": []}}))
        self.assert_has_issue_path(ctx.exception, "configuration.approval.reviewers")

        # Non-list reviewers
        with self.assertRaises(ConfigError) as ctx:
            approval_policy_from_project(make_profile({"approval": {"reviewers": "r1"}}))
        self.assert_has_issue_path(ctx.exception, "configuration.approval.reviewers")

        # Duplicate reviewers
        with self.assertRaises(ConfigError) as ctx:
            approval_policy_from_project(make_profile({"approval": {"reviewers": ["r1", "r1"]}}))
        self.assert_has_issue_path(ctx.exception, "configuration.approval.reviewers")

        # Empty reviewer string
        with self.assertRaises(ConfigError) as ctx:
            approval_policy_from_project(make_profile({"approval": {"reviewers": ["r1", ""]}}))
        self.assert_has_issue_path(ctx.exception, "configuration.approval.reviewers")

    def test_min_approvals_validation(self):
        # minApprovals > len(reviewers)
        with self.assertRaises(ConfigError) as ctx:
            approval_policy_from_project(
                make_profile({"approval": {"reviewers": ["r1"], "minApprovals": 2}})
            )
        self.assert_has_issue_path(ctx.exception, "configuration.approval.minApprovals")

        # minApprovals 0
        with self.assertRaises(ConfigError) as ctx:
            approval_policy_from_project(
                make_profile({"approval": {"reviewers": ["r1"], "minApprovals": 0}})
            )
        self.assert_has_issue_path(ctx.exception, "configuration.approval.minApprovals")

        # minApprovals non-integer
        with self.assertRaises(ConfigError) as ctx:
            approval_policy_from_project(
                make_profile({"approval": {"reviewers": ["r1"], "minApprovals": "one"}})
            )
        self.assert_has_issue_path(ctx.exception, "configuration.approval.minApprovals")

    def test_expires_in_seconds_validation(self):
        # expiresInSeconds 0
        with self.assertRaises(ConfigError) as ctx:
            approval_policy_from_project(
                make_profile({"approval": {"reviewers": ["r1"], "expiresInSeconds": 0}})
            )
        self.assert_has_issue_path(ctx.exception, "configuration.approval.expiresInSeconds")

        # expiresInSeconds non-integer
        with self.assertRaises(ConfigError) as ctx:
            approval_policy_from_project(
                make_profile({"approval": {"reviewers": ["r1"], "expiresInSeconds": "3600"}})
            )
        self.assert_has_issue_path(ctx.exception, "configuration.approval.expiresInSeconds")

    def test_every_config_error_carries_dotted_path(self):
        cases = [
            {},
            {"approval": None},
            {"approval": {}},
            {"approval": {"reviewers": []}},
            {"approval": {"reviewers": ["r1", "r1"]}},
            {"approval": {"reviewers": ["r1"], "minApprovals": 3}},
            {"approval": {"reviewers": ["r1"], "expiresInSeconds": 0}},
        ]
        for cfg in cases:
            with self.subTest(config=cfg):
                with self.assertRaises(ConfigError) as ctx:
                    approval_policy_from_project(make_profile(cfg))
                self.assertGreater(len(ctx.exception.issues), 0)
                for issue in ctx.exception.issues:
                    self.assertTrue(issue.path.startswith("configuration.approval"))
