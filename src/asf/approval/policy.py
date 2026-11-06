from __future__ import annotations

from asf.approval.mode import parse_approval_overrides
from asf.approval.models import (
    INVALID_REVIEWER_MESSAGE,
    ApprovalPolicy,
    validate_reviewer_identifier,
)
from asf.configuration.errors import ConfigError, ConfigIssue
from asf.configuration.project import ProjectProfile

__all__ = ["approval_policy_from_project"]


def _expires_in_seconds(approval_data: dict, issues: list[ConfigIssue]) -> int | None:
    if "expiresInSeconds" in approval_data:
        raw_exp = approval_data["expiresInSeconds"]
        exp_key = "expiresInSeconds"
    elif "expires_in_seconds" in approval_data:
        raw_exp = approval_data["expires_in_seconds"]
        exp_key = "expires_in_seconds"
    else:
        return None
    if type(raw_exp) is not int or raw_exp < 1:
        issues.append(
            ConfigIssue(
                path=f"configuration.approval.{exp_key}",
                message="expiresInSeconds must be an integer >= 1",
            )
        )
        return None
    return raw_exp


def approval_policy_from_project(profile: ProjectProfile) -> ApprovalPolicy:
    if not isinstance(profile.configuration, dict) or "approval" not in profile.configuration:
        raise ConfigError(
            issues=[
                ConfigIssue(
                    path="configuration.approval",
                    message="Missing approval configuration in project configuration",
                )
            ],
            source=None,
        )

    approval_data = profile.configuration["approval"]
    if not isinstance(approval_data, dict):
        raise ConfigError(
            issues=[
                ConfigIssue(
                    path="configuration.approval",
                    message="configuration.approval must be a mapping",
                )
            ],
            source=None,
        )

    issues: list[ConfigIssue] = []

    # Reviewers
    reviewers: list[str] = []
    if "reviewers" not in approval_data:
        issues.append(
            ConfigIssue(
                path="configuration.approval.reviewers",
                message="Missing reviewers in approval configuration",
            )
        )
    else:
        raw_reviewers = approval_data["reviewers"]
        if not isinstance(raw_reviewers, list) or isinstance(raw_reviewers, (str, bytes)):
            issues.append(
                ConfigIssue(
                    path="configuration.approval.reviewers",
                    message="Reviewers must be a list of non-empty strings",
                )
            )
        elif len(raw_reviewers) == 0:
            issues.append(
                ConfigIssue(
                    path="configuration.approval.reviewers",
                    message="Reviewers list must not be empty",
                )
            )
        else:
            has_invalid = False
            for r in raw_reviewers:
                try:
                    validate_reviewer_identifier(r)
                except ValueError:
                    has_invalid = True
                    break
            if has_invalid:
                issues.append(
                    ConfigIssue(
                        path="configuration.approval.reviewers",
                        message=INVALID_REVIEWER_MESSAGE,
                    )
                )
            elif len(raw_reviewers) != len(set(raw_reviewers)):
                issues.append(
                    ConfigIssue(
                        path="configuration.approval.reviewers",
                        message="Reviewers list must contain unique identifiers",
                    )
                )
            else:
                reviewers = raw_reviewers

    # minApprovals (default 1)
    min_approvals = 1
    if "minApprovals" in approval_data:
        raw_min = approval_data["minApprovals"]
        min_key = "minApprovals"
    elif "min_approvals" in approval_data:
        raw_min = approval_data["min_approvals"]
        min_key = "min_approvals"
    else:
        raw_min = None
        min_key = "minApprovals"

    if raw_min is not None:
        if type(raw_min) is not int or raw_min < 1:
            issues.append(
                ConfigIssue(
                    path=f"configuration.approval.{min_key}",
                    message="minApprovals must be an integer >= 1",
                )
            )
        else:
            min_approvals = raw_min

    # Check invariant minApprovals <= len(reviewers)
    if reviewers and min_approvals > len(reviewers):
        issues.append(
            ConfigIssue(
                path=f"configuration.approval.{min_key}",
                message=(
                    f"minApprovals ({min_approvals}) cannot exceed "
                    f"number of reviewers ({len(reviewers)})"
                ),
            )
        )

    expires_in_seconds = _expires_in_seconds(approval_data, issues)

    if issues:
        raise ConfigError(issues=issues, source=None)

    parse_approval_overrides(approval_data)  # Phase 12 keys; the human policy ignores them
    return ApprovalPolicy(
        min_approvals=min_approvals,
        reviewers=reviewers,
        expires_in_seconds=expires_in_seconds,
    )
