"""Run-start approval context (Phase 12).

Bakes a project profile's ``configuration.approval`` block into a
new run's context (key ``approval``) so gate resolution at run time
— mode, per-stage overrides, the human policy — reads the profile
as it was when the run started. Kept outside the commands mixin so
the mixin does not grow with the Phase 12 wiring.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from asf.approval.mode import parse_approval_overrides
from asf.approval.policy import approval_policy_from_project
from asf.configuration.project import ProjectProfile

__all__ = ["approval_context_for", "bake_approval_context", "merge_approval_context"]


def bake_approval_context(
    context: Mapping[str, Any] | None, profiles: Mapping[str, Any], project_id: str
) -> dict[str, Any]:
    """A copy of the run context with the project's approval baked in."""
    merged = dict(context or {})
    approval_context = approval_context_for(profiles, project_id)
    if approval_context is not None:
        merged["approval"] = merge_approval_context(merged.get("approval"), approval_context)
    return merged


def approval_context_for(profiles: Mapping[str, Any], project_id: str) -> dict[str, Any] | None:
    """The approval context a new run of this project starts with.

    Invalid Phase 12 keys fail the run start loudly (ConfigError);
    a project without an approval block gets no context and the
    workflow's own step settings apply.
    """
    profile = profiles.get(project_id) or {}
    configuration = profile.get("configuration")
    approval = configuration.get("approval") if isinstance(configuration, Mapping) else None
    if not isinstance(approval, Mapping):
        return None
    parse_approval_overrides(approval)
    context: dict[str, Any] = {"overrides": deepcopy(dict(approval))}
    if "reviewers" in approval:
        policy = approval_policy_from_project(ProjectProfile.model_validate(profile))
        context["policy"] = {
            "reviewers": list(policy.reviewers),
            "minApprovals": policy.min_approvals,
            "expiresInSeconds": policy.expires_in_seconds,
        }
    return context


def merge_approval_context(caller: Any, approval_context: Mapping[str, Any]) -> dict[str, Any]:
    """Merge the profile's approval context over the caller's.

    The profile wins each key it sets; inside ``overrides`` the
    merge is per key, so caller keys the profile does not mention
    (e.g. a mode pin next to the profile's channel) survive instead
    of being clobbered wholesale.
    """
    merged = dict(caller) if isinstance(caller, Mapping) else {}
    caller_overrides = merged.get("overrides")
    merged.update(approval_context)
    profile_overrides = approval_context.get("overrides")
    if isinstance(caller_overrides, Mapping) and isinstance(profile_overrides, Mapping):
        combined = dict(caller_overrides)
        combined.update(profile_overrides)
        merged["overrides"] = combined
    return merged
