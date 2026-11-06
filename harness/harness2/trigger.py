"""Improvement trigger: which agent deserves a Harness² improvement cycle.

This is **not** the Harness² method. It is a deterministic, offline
threshold scan over runtime metrics that answers one question: where
would an improvement cycle (the loop in `docs/architecture/harness2.md`)
be worth its cost? It makes no network calls and proposes no harness
edits itself.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "HEALTH_SCORE_MIN",
    "AVG_REVISIONS_MAX",
    "HUMAN_APPROVAL_RATE_MIN",
    "TEST_PASS_RATE_MIN",
    "AgentMetricsRow",
    "HumanMetrics",
    "ImprovementTrigger",
    "MetricsImprovementTrigger",
    "MetricsOverview",
    "NullImprovementTrigger",
    "QualityMetrics",
    "Suggestion",
    "default_trigger",
]

HEALTH_SCORE_MIN = 70.0
AVG_REVISIONS_MAX = 1.5
HUMAN_APPROVAL_RATE_MIN = 0.5
TEST_PASS_RATE_MIN = 0.8


class AgentMetricsRow(BaseModel):
    """One agent's row of a metrics overview (dashboard camelCase aliases)."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    agent_id: str = Field(default="unknown", alias="agentId")
    success_rate: float | None = Field(default=None, alias="successRate")
    avg_revisions: float | None = Field(default=None, alias="avgRevisions")
    human_approval_rate: float | None = Field(default=None, alias="humanApprovalRate")
    health_score: float | None = Field(default=None, alias="healthScore")


class HumanMetrics(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    approval_rate: float | None = Field(default=None, alias="approvalRate")


class QualityMetrics(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    test_pass_rate: float | None = Field(default=None, alias="testPassRate")


class MetricsOverview(BaseModel):
    """Typed replacement for the old `dict[str, Any]` metrics overview."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    agents: list[AgentMetricsRow] = Field(default_factory=list)
    human: HumanMetrics = Field(default_factory=HumanMetrics)
    quality: QualityMetrics = Field(default_factory=QualityMetrics)


class Suggestion(BaseModel):
    """One improvement suggestion derived from runtime metrics."""

    model_config = ConfigDict(extra="forbid")

    target_agent_id: str
    kind: str
    message: str
    metric: str
    value: float


@runtime_checkable
class ImprovementTrigger(Protocol):
    """Anything that can scan metrics and suggest improvement targets."""

    available: bool

    def assess(self, overview: MetricsOverview) -> list[Suggestion]:
        """Return improvement suggestions for a metrics overview."""
        ...


class NullImprovementTrigger:
    """Default trigger: improvement cycles are off, so it suggests nothing."""

    available = False

    def assess(self, overview: MetricsOverview) -> list[Suggestion]:
        return []


def _health_suggestion(row: AgentMetricsRow) -> Suggestion | None:
    health = row.health_score
    if health is None or health >= HEALTH_SCORE_MIN:
        return None
    return Suggestion(
        target_agent_id=row.agent_id,
        kind="investigate_agent",
        message=f"Agent {row.agent_id} health score is below 70; investigate it.",
        metric="healthScore",
        value=float(health),
    )


def _revisions_suggestion(row: AgentMetricsRow) -> Suggestion | None:
    revisions = row.avg_revisions
    if revisions is None or revisions <= AVG_REVISIONS_MAX:
        return None
    return Suggestion(
        target_agent_id=row.agent_id,
        kind="tighten_prompt_or_template",
        message=(
            f"Agent {row.agent_id} averages more than 1.5 revisions; "
            "tighten its prompt or spec template."
        ),
        metric="avgRevisions",
        value=float(revisions),
    )


def _agent_approval_suggestion(row: AgentMetricsRow) -> Suggestion | None:
    approval = row.human_approval_rate
    if approval is None or approval >= HUMAN_APPROVAL_RATE_MIN:
        return None
    return Suggestion(
        target_agent_id=row.agent_id,
        kind="review_artifact_template",
        message=(
            f"Agent {row.agent_id} is approved by humans less than half the "
            "time; review its artifact template."
        ),
        metric="humanApprovalRate",
        value=float(approval),
    )


def _overall_approval_suggestion(overview: MetricsOverview) -> Suggestion | None:
    rate = overview.human.approval_rate
    if rate is None or rate >= HUMAN_APPROVAL_RATE_MIN:
        return None
    return Suggestion(
        target_agent_id="all",
        kind="review_artifact_template",
        message="Overall human approval rate is below 0.5; review artifact templates.",
        metric="human.approvalRate",
        value=float(rate),
    )


def _test_pass_suggestion(overview: MetricsOverview) -> Suggestion | None:
    rate = overview.quality.test_pass_rate
    if rate is None or rate >= TEST_PASS_RATE_MIN:
        return None
    return Suggestion(
        target_agent_id="all",
        kind="strengthen_test_generation",
        message="Test pass rate is below 0.8; strengthen test generation.",
        metric="quality.testPassRate",
        value=float(rate),
    )


def _agent_suggestions(row: AgentMetricsRow) -> list[Suggestion]:
    checks = (_health_suggestion, _revisions_suggestion, _agent_approval_suggestion)
    return [s for check in checks if (s := check(row)) is not None]


class MetricsImprovementTrigger:
    """Deterministic offline threshold rules over a metrics overview.

    Missing values are skipped, not guessed.
    """

    available = True

    def assess(self, overview: MetricsOverview) -> list[Suggestion]:
        suggestions: list[Suggestion] = []
        for row in overview.agents:
            suggestions.extend(_agent_suggestions(row))
        for check in (_overall_approval_suggestion, _test_pass_suggestion):
            suggestion = check(overview)
            if suggestion is not None:
                suggestions.append(suggestion)
        return suggestions


def default_trigger() -> ImprovementTrigger:
    """Return the default trigger: improvement cycles stay off by default."""
    return NullImprovementTrigger()
