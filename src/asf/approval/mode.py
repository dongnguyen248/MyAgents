"""Approval-mode resolution for gated workflow steps.

A gated step's gate can be decided by a human (the historical default),
by the AI artifact-review loop, or by nobody (mode ``none``). The
effective settings come from four layers, highest precedence first:
the profile's per-stage override, the profile's ``configuration.approval``
block, the workflow step's own approval block, and the built-in default.
This module is the single place that parses and resolves those layers;
it performs no I/O.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from asf.approval.models import ApprovalPolicy
from asf.configuration.errors import ConfigError, ConfigIssue

__all__ = [
    "APPROVAL_MODES",
    "DEFAULT_BLOCK_ON",
    "DEFAULT_MAX_REVIEW_ROUNDS",
    "FINDING_SEVERITIES",
    "ON_EXHAUSTED_ACTIONS",
    "ApprovalOverrides",
    "ResolvedApproval",
    "StepGate",
    "approval_overrides_from_context",
    "approval_policy_from_context",
    "max_review_rounds_from_context",
    "parse_approval_overrides",
    "resolve_approval_mode",
]

APPROVAL_MODES = ("ai", "human", "none")
ON_EXHAUSTED_ACTIONS = ("escalate", "accept_with_warnings")
FINDING_SEVERITIES = ("BLOCKER", "MAJOR", "MINOR", "NIT")
DEFAULT_BLOCK_ON = ("BLOCKER", "MAJOR")
DEFAULT_ON_EXHAUSTED = "escalate"
MIN_PROFILE_MAX_REVISIONS = 1
MAX_PROFILE_MAX_REVISIONS = 10
DEFAULT_MAX_REVIEW_ROUNDS = 12

# Resolve-time revision defaults. They mirror the parse-time defaults in
# asf.workflow.definition, which this package must not import (purity
# guard); a unit test pins the two pairs together.
DEFAULT_HUMAN_MAX_REVISIONS = 3
DEFAULT_AI_MAX_REVISIONS = 4


class StepGate(Protocol):
    """The step fields the resolver reads; WorkflowStepDef satisfies it."""

    @property
    def id(self) -> str: ...

    @property
    def approval_mode(self) -> str: ...

    @property
    def max_revisions(self) -> int | None: ...

    @property
    def max_revisions_explicit(self) -> bool: ...


@dataclass(frozen=True)
class ApprovalOverrides:
    """The approval keys one profile layer may set; unset means inherit."""

    mode: str | None = None
    max_revisions: int | None = None
    on_exhausted: str | None = None
    block_on: tuple[str, ...] | None = None
    per_stage: dict[str, ApprovalOverrides] = field(default_factory=dict)


@dataclass(frozen=True)
class ResolvedApproval:
    """The fully resolved gate settings for one step of one project."""

    mode: str
    max_revisions: int
    on_exhausted: str
    block_on: tuple[str, ...]


def _pick(data: Mapping[str, Any], camel: str, snake: str) -> Any:
    if camel in data:
        return data[camel]
    return data.get(snake)


def _check_mode(raw: Any, path: str, issues: list[ConfigIssue]) -> str | None:
    if raw is None:
        return None
    if raw not in APPROVAL_MODES:
        issues.append(ConfigIssue(path=path, message=f"mode must be one of {APPROVAL_MODES}"))
        return None
    return str(raw)


def _check_max_revisions(raw: Any, path: str, issues: list[ConfigIssue]) -> int | None:
    if raw is None:
        return None
    if type(raw) is not int or not MIN_PROFILE_MAX_REVISIONS <= raw <= MAX_PROFILE_MAX_REVISIONS:
        message = (
            f"maxRevisions must be an integer between {MIN_PROFILE_MAX_REVISIONS} "
            f"and {MAX_PROFILE_MAX_REVISIONS}"
        )
        issues.append(ConfigIssue(path=path, message=message))
        return None
    return raw


def _check_on_exhausted(raw: Any, path: str, issues: list[ConfigIssue]) -> str | None:
    if raw is None:
        return None
    if raw not in ON_EXHAUSTED_ACTIONS:
        issues.append(
            ConfigIssue(path=path, message=f"onExhausted must be one of {ON_EXHAUSTED_ACTIONS}")
        )
        return None
    return str(raw)


def _check_block_on(raw: Any, path: str, issues: list[ConfigIssue]) -> tuple[str, ...] | None:
    if raw is None:
        return None
    if not isinstance(raw, list) or any(item not in FINDING_SEVERITIES for item in raw):
        issues.append(
            ConfigIssue(path=path, message=f"blockOn entries must be among {FINDING_SEVERITIES}")
        )
        return None
    return tuple(dict.fromkeys(raw))


def parse_approval_overrides(
    data: Mapping[str, Any] | None, *, path: str = "configuration.approval"
) -> ApprovalOverrides:
    """Validate the Phase 12 approval keys of one profile approval block.

    Raises ConfigError listing every invalid key. Unknown keys are
    ignored, matching the existing approval-policy behaviour.
    """
    if data is None:
        return ApprovalOverrides()
    issues: list[ConfigIssue] = []
    overrides = ApprovalOverrides(
        mode=_check_mode(_pick(data, "mode", "mode"), f"{path}.mode", issues),
        max_revisions=_check_max_revisions(
            _pick(data, "maxRevisions", "max_revisions"), f"{path}.maxRevisions", issues
        ),
        on_exhausted=_check_on_exhausted(
            _pick(data, "onExhausted", "on_exhausted"), f"{path}.onExhausted", issues
        ),
        block_on=_check_block_on(_pick(data, "blockOn", "block_on"), f"{path}.blockOn", issues),
        per_stage=_parse_per_stage(data, path, issues),
    )
    if issues:
        raise ConfigError(issues=issues, source=None)
    return overrides


def _parse_per_stage(
    data: Mapping[str, Any], path: str, issues: list[ConfigIssue]
) -> dict[str, ApprovalOverrides]:
    raw = _pick(data, "perStage", "per_stage")
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        issues.append(ConfigIssue(path=f"{path}.perStage", message="perStage must be a mapping"))
        return {}
    parsed: dict[str, ApprovalOverrides] = {}
    for step_id, entry in raw.items():
        if not isinstance(entry, Mapping):
            message = "per-stage override must be a mapping"
            issues.append(ConfigIssue(path=f"{path}.perStage.{step_id}", message=message))
            continue
        parsed[str(step_id)] = parse_approval_overrides(entry, path=f"{path}.perStage.{step_id}")
    return parsed


def _step_max_revisions(step: StepGate, mode: str) -> int:
    if step.max_revisions is not None and step.max_revisions_explicit:
        return step.max_revisions
    if mode == "ai":
        return DEFAULT_AI_MAX_REVISIONS
    if step.max_revisions is not None:
        return step.max_revisions
    return DEFAULT_HUMAN_MAX_REVISIONS


def _with_blocker(block_on: tuple[str, ...]) -> tuple[str, ...]:
    return ("BLOCKER", *(item for item in block_on if item != "BLOCKER"))


def approval_overrides_from_context(context: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """The profile approval block baked into a run's context at start.

    The API service stores the project's raw ``configuration.approval``
    mapping under context key ``approval`` / ``overrides`` when a run is
    created, so gate resolution at run time needs no profile access.
    """
    approval = context.get("approval")
    if not isinstance(approval, Mapping):
        return None
    overrides = approval.get("overrides")
    return overrides if isinstance(overrides, Mapping) else None


def approval_policy_from_context(context: Mapping[str, Any]) -> ApprovalPolicy | None:
    """The project's human approval policy baked into the run context.

    Resolved from the profile at run start (see
    ``approval_policy_from_project``); None when the project configured
    no reviewers, in which case the engine's base policy applies.
    """
    approval = context.get("approval")
    if not isinstance(approval, Mapping):
        return None
    raw = approval.get("policy")
    if not isinstance(raw, Mapping) or not isinstance(raw.get("reviewers"), list):
        return None
    expires = raw.get("expiresInSeconds")
    return ApprovalPolicy(
        reviewers=[str(item) for item in raw["reviewers"]],
        min_approvals=int(raw.get("minApprovals") or 1),
        expires_in_seconds=expires if type(expires) is int else None,
    )


def max_review_rounds_from_context(context: Mapping[str, Any]) -> int:
    """The per-run AI review round cap baked into the run context."""
    approval = context.get("approval")
    if isinstance(approval, Mapping):
        raw = approval.get("maxReviewRounds")
        if type(raw) is int and raw >= 1:
            return raw
    return DEFAULT_MAX_REVIEW_ROUNDS


def resolve_approval_mode(step: StepGate, approval: Mapping[str, Any] | None) -> ResolvedApproval:
    """Resolve one step's gate settings for one project's approval block."""
    overrides = parse_approval_overrides(approval)
    stage = overrides.per_stage.get(step.id, ApprovalOverrides())
    mode = stage.mode or overrides.mode or step.approval_mode
    max_revisions = stage.max_revisions
    if max_revisions is None:
        max_revisions = overrides.max_revisions
    if max_revisions is None:
        max_revisions = _step_max_revisions(step, mode)
    block_on = stage.block_on
    if block_on is None:
        block_on = overrides.block_on
    if block_on is None:
        block_on = DEFAULT_BLOCK_ON
    return ResolvedApproval(
        mode=mode,
        max_revisions=max_revisions,
        on_exhausted=stage.on_exhausted or overrides.on_exhausted or DEFAULT_ON_EXHAUSTED,
        block_on=_with_blocker(block_on),
    )
