"""Verdict and convergence logic for the artifact-review loop.

Pure functions over validated findings. The model never supplies a
verdict: code derives it from the findings, so a reviewer cannot
approve past its own open blockers, silently drop a previous problem,
or stall the loop with fresh nit-picking.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal

from asf.agents.artifact_review.prompts import Finding
from asf.contracts.models import Artifact

__all__ = [
    "DEFAULT_BLOCK_ON",
    "OPEN_STATUSES",
    "STAGNATION_CHANGE_THRESHOLD",
    "RoundOutcome",
    "artifact_hash",
    "carry_forward_findings",
    "derive_verdict",
    "detect_regression",
    "detect_stagnation",
    "open_blocking",
]

DEFAULT_BLOCK_ON = ("BLOCKER", "MAJOR")
OPEN_STATUSES = ("NEW", "STILL_OPEN")
MINOR_SEVERITIES = ("MINOR", "NIT")
# Below this fraction of changed content, a round counts as
# "the artifact barely moved" for stagnation purposes.
STAGNATION_CHANGE_THRESHOLD = 0.02
# The bias guard applies from the second review round onward.
BIAS_GUARD_MIN_ROUND = 2

Verdict = Literal["APPROVE", "REQUEST_CHANGES"]


@dataclass(frozen=True)
class RoundOutcome:
    """One completed review round, for convergence comparisons."""

    findings: tuple[Finding, ...]
    artifact_hash: str
    change_ratio: float = 0.0


def artifact_hash(artifact: Artifact) -> str:
    """Stable hash of an artifact's content, for stagnation checks."""
    canonical = json.dumps(artifact.content, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def open_blocking(findings: list[Finding], block_on: tuple[str, ...]) -> list[Finding]:
    """Open findings whose severity blocks approval (pre bias-guard)."""
    return [
        finding
        for finding in findings
        if finding.status in OPEN_STATUSES and finding.severity in block_on
    ]


def _blocks(finding: Finding, block_on: tuple[str, ...], round_number: int) -> bool:
    if finding.status not in OPEN_STATUSES or finding.severity not in block_on:
        return False
    if round_number < BIAS_GUARD_MIN_ROUND or finding.source != "ai":
        return True
    # Bias guard: a minor issue the reviewer only noticed in a later
    # round must not extend the loop; round-1 minors still block when
    # the project configured them to.
    return not (finding.status == "NEW" and finding.severity in MINOR_SEVERITIES)


def derive_verdict(
    findings: list[Finding],
    block_on: tuple[str, ...] = DEFAULT_BLOCK_ON,
    *,
    round_number: int = 1,
) -> Verdict:
    """APPROVE iff no open finding blocks under the configured severities."""
    if any(_blocks(finding, block_on, round_number) for finding in findings):
        return "REQUEST_CHANGES"
    return "APPROVE"


def carry_forward_findings(previous: list[Finding], current: list[Finding]) -> list[Finding]:
    """Re-add unmentioned still-open previous findings as STILL_OPEN.

    A finding the model resolved or waived in an earlier round stays
    closed; one it simply forgot stays open, so problems cannot be
    dropped by silence.
    """
    mentioned = {finding.id for finding in current}
    merged = list(current)
    for finding in previous:
        if finding.id not in mentioned and finding.status in OPEN_STATUSES:
            merged.append(finding.model_copy(update={"status": "STILL_OPEN"}))
    return merged


def detect_regression(previous: list[Finding], current: list[Finding]) -> list[str]:
    """Ids of findings that were RESOLVED before and are open again."""
    resolved_before = {finding.id for finding in previous if finding.status == "RESOLVED"}
    open_now = {finding.id for finding in current if finding.status in OPEN_STATUSES}
    return sorted(resolved_before & open_now)


def _open_blocking_ids(outcome: RoundOutcome, block_on: tuple[str, ...]) -> set[str]:
    return {finding.id for finding in open_blocking(list(outcome.findings), block_on)}


def detect_stagnation(
    previous: RoundOutcome,
    current: RoundOutcome,
    *,
    block_on: tuple[str, ...] = DEFAULT_BLOCK_ON,
) -> bool:
    """True when a round made no real progress on the blocking set."""
    if current.artifact_hash == previous.artifact_hash:
        return True
    if current.change_ratio >= STAGNATION_CHANGE_THRESHOLD:
        return False
    previous_ids = _open_blocking_ids(previous, block_on)
    current_ids = _open_blocking_ids(current, block_on)
    return bool(previous_ids) and previous_ids == current_ids
