"""Pure aggregation helpers for the evaluation service.

Everything here is a function of plain record lists — no clock,
no lock, no service state — so the dashboard shapes (agent
metrics, the human overview section, the AI review block) can be
computed and tested without a MetricsService instance.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from asf.contracts.models import ActivityEvent
from asf.evaluation.models import AgentRunRecord, ApprovalRecord

__all__ = [
    "HealthInputs",
    "agent_metrics_view",
    "ai_decision_record",
    "ai_review_metrics",
    "health_score",
    "human_section",
    "mean",
    "rate",
]

_FAILED_STATUSES = ("FAILED", "REJECTED")
_AI_ESCALATION_REASONS = ("MAX_REVISIONS", "NO_PROGRESS", "REVIEWER_FAILED", "BUDGET")


def rate(numerator: int, denominator: int) -> float:
    """Return a 0..1 rate; a zero denominator is defined as 0.0 (never NaN)."""
    return numerator / denominator if denominator else 0.0


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


@dataclass(frozen=True)
class HealthInputs:
    """The rates a health score is computed from."""

    success_rate: float
    human_approval_rate: float | None
    ci_pass_rate: float
    test_pass_rate: float
    avg_revisions: float


def health_score(inputs: HealthInputs) -> int:
    """Mirror ``apps/dashboard/src/utils/health.ts`` exactly (weights and rounding).

    ``Math.round`` in the dashboard rounds halves up; the score is never
    negative, so ``floor(x + 0.5)`` reproduces it. The revision term follows
    the dashboard formula literally, including for ``avg_revisions == 0``.

    When the agent has no human decisions (``human_approval_rate is
    None`` — the normal case for AI-reviewed gates), the human
    component is not scored as zero: the remaining weights are
    re-normalised to sum to 1 (divided by 0.80).
    """
    revision_score = max(0.0, 1.0 - (inputs.avg_revisions - 1.0) / 3.0)
    if inputs.human_approval_rate is None:
        weighted = (
            0.30 * inputs.success_rate
            + 0.20 * inputs.ci_pass_rate
            + 0.15 * inputs.test_pass_rate
            + 0.15 * revision_score
        ) / 0.80
    else:
        weighted = (
            0.30 * inputs.success_rate
            + 0.20 * inputs.human_approval_rate
            + 0.20 * inputs.ci_pass_rate
            + 0.15 * inputs.test_pass_rate
            + 0.15 * revision_score
        )
    return int(math.floor(weighted * 100 + 0.5))


def _status_counts(runs: list[AgentRunRecord]) -> dict[str, int]:
    return {
        "total": len(runs),
        "completed": sum(1 for run in runs if run.status == "SUCCESS"),
        "running": sum(1 for run in runs if run.status == "WAITING"),
        "failed": sum(1 for run in runs if run.status in _FAILED_STATUSES),
        "cancelled": sum(1 for run in runs if run.status == "CANCELLED"),
    }


def _run_counts(runs: list[AgentRunRecord]) -> dict[str, Any]:
    counts: dict[str, Any] = dict(_status_counts(runs))
    counts["successRate"] = rate(counts["completed"], counts["total"])
    counts["avgDurationSec"] = mean([run.duration_seconds for run in runs])
    counts["avgRevisions"] = mean([float(run.revision_count) for run in runs])
    counts["promptTokens"] = sum(run.prompt_tokens for run in runs)
    counts["completionTokens"] = sum(run.completion_tokens for run in runs)
    counts["modelCalls"] = sum(run.model_calls for run in runs)
    return counts


def agent_metrics_view(
    runs: list[AgentRunRecord],
    approvals: list[ApprovalRecord],
    *,
    test_pass_rate: float,
    ci_pass_rate: float,
) -> dict[str, Any]:
    """The dashboard ``AgentMetrics`` dict for one agent's records."""
    human = [item for item in approvals if item.reviewer_kind == "HUMAN"]
    metrics = _run_counts(runs)
    # Human-only by construction: AI decisions are recorded with
    # reviewer_kind AI and never enter this rate. With no human
    # decisions the rate is None (not 0.0) and the health score
    # re-normalises without the human weight.
    metrics["humanApprovalRate"] = (
        rate(sum(1 for item in human if item.decision == "APPROVED"), len(human)) if human else None
    )
    metrics["humanDecisions"] = len(human)
    metrics["aiDecisions"] = sum(1 for item in approvals if item.reviewer_kind == "AI")
    metrics["testPassRate"] = test_pass_rate
    metrics["ciPassRate"] = ci_pass_rate
    metrics["healthScore"] = health_score(
        HealthInputs(
            success_rate=metrics["successRate"],
            human_approval_rate=metrics["humanApprovalRate"],
            ci_pass_rate=ci_pass_rate,
            test_pass_rate=test_pass_rate,
            avg_revisions=metrics["avgRevisions"],
        )
    )
    return metrics


def _human_daily(human_records: list[ApprovalRecord]) -> list[dict[str, Any]]:
    by_date: dict[str, list[ApprovalRecord]] = {}
    for item in human_records:
        by_date.setdefault(item.recorded_at.date().isoformat(), []).append(item)
    return [
        {
            "date": date,
            "approvalRate": rate(
                sum(1 for i in day_items if i.decision == "APPROVED"), len(day_items)
            ),
            "rejectionRate": rate(
                sum(1 for i in day_items if i.decision != "APPROVED"), len(day_items)
            ),
        }
        for date, day_items in sorted(by_date.items())
    ]


def _decision_rate(records: list[ApprovalRecord], *, approved: bool) -> float | None:
    if not records:
        return None
    hits = sum(1 for item in records if (item.decision == "APPROVED") is approved)
    return rate(hits, len(records))


def human_section(approvals: list[ApprovalRecord], runs: list[AgentRunRecord]) -> dict[str, Any]:
    """The overview's ``human`` block, from HUMAN decisions only.

    With no human decisions at all the rates are None (undefined),
    never 0.0 — a 0.0 would read as "humans reject everything"
    and fire the harness improvement trigger.
    """
    human_records = [item for item in approvals if item.reviewer_kind == "HUMAN"]
    return {
        "approvalRate": _decision_rate(human_records, approved=True),
        "rejectionRate": _decision_rate(human_records, approved=False),
        "decisions": len(human_records),
        "aiDecisions": sum(1 for i in approvals if i.reviewer_kind == "AI"),
        "avgRevisions": mean([float(run.revision_count) for run in runs]),
        # Approval *durations* are not tracked (record_approval_decision
        # receives no request time), so this stays 0.0 by definition.
        "avgApprovalMinutes": 0.0,
        "daily": _human_daily(human_records),
    }


def ai_decision_record(event: ActivityEvent) -> ApprovalRecord | None:
    """An AI_REVIEW_COMPLETED event as an AI approval decision record.

    Recording it (reviewer kind AI, attributed to the reviewer
    agent) keeps AI decisions auditable in the same ledger as
    human ones without ever entering the human approval rate.
    """
    if event.event_type != "AI_REVIEW_COMPLETED":
        return None
    verdict = event.metadata.get("verdict")
    if verdict not in ("APPROVE", "REQUEST_CHANGES"):
        return None
    return ApprovalRecord(
        recorded_at=event.timestamp,
        project_id=event.project_id,
        task_id=event.task_id,
        agent_id=event.agent_id or "agent-artifact-review",
        decision="APPROVED" if verdict == "APPROVE" else "REQUEST_CHANGES",
        reviewer_kind="AI",
    )


@dataclass
class _GateTally:
    gates: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    escalated: set[tuple[str, str]] = field(default_factory=set)
    stagnated: set[tuple[str, str]] = field(default_factory=set)


def _tally_event(tally: _GateTally, event: ActivityEvent) -> None:
    key = (event.workflow_id or "", str(event.metadata.get("stepId") or ""))
    if event.event_type == "AI_REVIEW_COMPLETED":
        gate = tally.gates.setdefault(key, {"rounds": 0, "first": None, "approved": False})
        gate["rounds"] += 1
        if gate["first"] is None:
            gate["first"] = event.metadata.get("verdict")
        if event.metadata.get("verdict") == "APPROVE":
            gate["approved"] = True
    elif event.event_type == "WORKFLOW_ESCALATED":
        if event.metadata.get("reason") in _AI_ESCALATION_REASONS:
            tally.escalated.add(key)
    elif event.event_type == "AI_REVIEW_STAGNATION":
        tally.stagnated.add(key)


def ai_review_metrics(events: list[ActivityEvent]) -> dict[str, Any]:
    """AI review loop metrics, computed from the published events.

    A *gate* is one (run, step) with at least one completed
    AI review round. firstPassRate: gates whose first round
    approved. avgRounds: completed rounds per gate.
    escalationRate: gates escalated for an AI reason over
    gates that reached an outcome (approved or escalated).
    stagnationRate: gates that hit stagnation over all gates.
    """
    tally = _GateTally()
    for event in events:
        _tally_event(tally, event)
    gates = tally.gates
    decided = {key for key, gate in gates.items() if gate["approved"]} | tally.escalated
    return {
        "firstPassRate": rate(
            sum(1 for gate in gates.values() if gate["first"] == "APPROVE"), len(gates)
        ),
        "avgRounds": mean([float(gate["rounds"]) for gate in gates.values()]),
        "escalationRate": rate(len(tally.escalated), len(decided)),
        "stagnationRate": rate(len(tally.stagnated & set(gates)), len(gates)),
        "gates": len(gates),
        "escalations": len(tally.escalated),
    }
