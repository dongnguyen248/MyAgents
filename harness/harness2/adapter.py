"""Harness² adapter seam.

Google Harness² (recursive improvement) is NOT integrated: there are no
network calls here. The seam exists so a real adapter can be dropped in
later without touching callers. The default adapter is the null one;
:class:`LocalHarness2Adapter` is a deterministic, offline stand-in that
applies simple rules to a runtime metrics overview.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

__all__ = [
    "Harness2Adapter",
    "LocalHarness2Adapter",
    "NullHarness2Adapter",
    "Suggestion",
    "default_adapter",
]


class Suggestion(BaseModel):
    """One improvement suggestion derived from runtime metrics."""

    model_config = ConfigDict(extra="forbid")

    target_agent_id: str
    kind: str
    message: str
    metric: str
    value: float


@runtime_checkable
class Harness2Adapter(Protocol):
    """Anything that can assess a metrics overview and suggest improvements."""

    available: bool

    def assess(self, metrics_overview: dict[str, Any]) -> list[Suggestion]:
        """Return improvement suggestions for a MetricsOverview-shaped dict."""
        ...


class NullHarness2Adapter:
    """Default adapter: Harness² is off, so it never suggests anything."""

    available = False

    def assess(self, metrics_overview: dict[str, Any]) -> list[Suggestion]:
        return []


class LocalHarness2Adapter:
    """Deterministic offline rules over a MetricsOverview-shaped dict.

    Expected shape (see ``apps/dashboard/src/types/metrics.ts``): ``agents``
    rows with ``agentId`` / ``successRate`` / ``avgRevisions`` /
    ``humanApprovalRate`` / ``healthScore``, plus ``human.approvalRate``
    and ``quality.testPassRate``. Missing values are skipped, not guessed.
    """

    available = True

    def assess(self, metrics_overview: dict[str, Any]) -> list[Suggestion]:
        suggestions: list[Suggestion] = []
        for row in metrics_overview.get("agents") or []:
            agent_id = str(row.get("agentId", "unknown"))
            health = row.get("healthScore")
            if health is not None and health < 70:
                suggestions.append(
                    Suggestion(
                        target_agent_id=agent_id,
                        kind="investigate_agent",
                        message=f"Agent {agent_id} health score is below 70; investigate it.",
                        metric="healthScore",
                        value=float(health),
                    )
                )
            revisions = row.get("avgRevisions")
            if revisions is not None and revisions > 1.5:
                suggestions.append(
                    Suggestion(
                        target_agent_id=agent_id,
                        kind="tighten_prompt_or_template",
                        message=(
                            f"Agent {agent_id} averages more than 1.5 revisions; "
                            "tighten its prompt or spec template."
                        ),
                        metric="avgRevisions",
                        value=float(revisions),
                    )
                )
            approval = row.get("humanApprovalRate")
            if approval is not None and approval < 0.5:
                suggestions.append(
                    Suggestion(
                        target_agent_id=agent_id,
                        kind="review_artifact_template",
                        message=(
                            f"Agent {agent_id} is approved by humans less than half the "
                            "time; review its artifact template."
                        ),
                        metric="humanApprovalRate",
                        value=float(approval),
                    )
                )
        human = metrics_overview.get("human") or {}
        approval_rate = human.get("approvalRate")
        if approval_rate is not None and approval_rate < 0.5:
            suggestions.append(
                Suggestion(
                    target_agent_id="all",
                    kind="review_artifact_template",
                    message="Overall human approval rate is below 0.5; review artifact templates.",
                    metric="human.approvalRate",
                    value=float(approval_rate),
                )
            )
        quality = metrics_overview.get("quality") or {}
        test_pass = quality.get("testPassRate")
        if test_pass is not None and test_pass < 0.8:
            suggestions.append(
                Suggestion(
                    target_agent_id="all",
                    kind="strengthen_test_generation",
                    message="Test pass rate is below 0.8; strengthen test generation.",
                    metric="quality.testPassRate",
                    value=float(test_pass),
                )
            )
        return suggestions


def default_adapter() -> Harness2Adapter:
    """Return the default adapter: Harness² stays optional and off."""
    return NullHarness2Adapter()
