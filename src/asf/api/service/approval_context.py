"""Run-start approval context (Phase 12).

Bakes a project profile's ``configuration.approval`` block into a
new run's context (key ``approval``) so gate resolution at run time
— mode, per-stage overrides, the human policy — reads the profile
as it was when the run started. Kept outside the commands mixin so
the mixin does not grow with the Phase 12 wiring.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from contextlib import suppress
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from asf.approval.mode import parse_approval_overrides
from asf.approval.policy import approval_policy_from_project
from asf.configuration.project import ProjectProfile
from asf.evaluation.models import ApprovalDecisionRecord

logger = logging.getLogger(__name__)

__all__ = [
    "DecisionRecord",
    "approval_context_for",
    "bake_approval_context",
    "merge_approval_context",
    "record_decision",
]


@dataclass(frozen=True)
class DecisionRecord:
    """One approval decision to forward to the metrics sink."""

    project_id: str
    task_id: str | None
    agent_id: str | None
    decision: str
    reviewer_kind: str = "HUMAN"


def record_decision(metrics: Any, item: DecisionRecord) -> None:
    """Forward one approval decision to the metrics sink, if it takes them.

    Older sinks without the ``reviewer_kind`` parameter are retried
    without it; a failing sink never breaks the decision itself.
    """
    if not item.agent_id:
        return
    if metrics is None or not hasattr(metrics, "record_approval_decision"):
        return
    _call_sink(metrics.record_approval_decision, item)


def _call_sink(record: Any, item: DecisionRecord) -> None:
    try:
        record(
            ApprovalDecisionRecord(
                project_id=item.project_id,
                task_id=item.task_id,
                agent_id=item.agent_id or "",
                decision=item.decision,
                reviewer_kind=item.reviewer_kind,
            )
        )
    except TypeError:
        _call_sink_kwargs(record, item)
    except Exception:
        logger.exception("Approval metrics sink failed; decision itself already applied")


def _call_sink_kwargs(record: Any, item: DecisionRecord) -> None:
    """Fallback for sinks that still take the decision as keywords."""
    try:
        record(
            project_id=item.project_id,
            task_id=item.task_id,
            agent_id=item.agent_id,
            decision=item.decision,
            reviewer_kind=item.reviewer_kind,
            at=None,
        )
    except TypeError:
        with suppress(Exception):
            record(
                project_id=item.project_id,
                task_id=item.task_id,
                agent_id=item.agent_id,
                decision=item.decision,
            )
    except Exception:
        logger.exception("Approval metrics sink failed; decision itself already applied")


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
