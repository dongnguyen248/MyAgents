"""Tests for the improvement trigger (null default + metrics rules)."""

from harness.harness2 import (
    MetricsImprovementTrigger,
    MetricsOverview,
    NullImprovementTrigger,
    Suggestion,
    default_trigger,
)


def _overview(**overrides):
    data = {
        "agents": [],
        "human": {"approvalRate": 0.9},
        "quality": {"testPassRate": 0.95},
    }
    data.update(overrides)
    return MetricsOverview.model_validate(data)


def test_null_trigger_is_default_and_suggests_nothing():
    trigger = default_trigger()
    assert isinstance(trigger, NullImprovementTrigger)
    assert trigger.available is False
    assert trigger.assess(_overview()) == []
    assert trigger.assess(MetricsOverview()) == []


def test_metrics_trigger_quiet_on_healthy_overview():
    trigger = MetricsImprovementTrigger()
    assert trigger.available is True
    overview = _overview(
        agents=[
            {
                "agentId": "agent-spec",
                "successRate": 0.99,
                "avgRevisions": 0.4,
                "humanApprovalRate": 0.95,
                "healthScore": 92,
            }
        ]
    )
    assert trigger.assess(overview) == []


def test_metrics_trigger_agent_rules_fire():
    trigger = MetricsImprovementTrigger()
    overview = _overview(
        agents=[
            {
                "agentId": "agent-plan",
                "successRate": 0.6,
                "avgRevisions": 2.3,
                "humanApprovalRate": 0.3,
                "healthScore": 55,
            }
        ]
    )
    suggestions = trigger.assess(overview)
    by_metric = {s.metric: s for s in suggestions}
    assert set(by_metric) == {"healthScore", "avgRevisions", "humanApprovalRate"}
    assert by_metric["healthScore"].kind == "investigate_agent"
    assert by_metric["healthScore"].value == 55
    assert by_metric["avgRevisions"].kind == "tighten_prompt_or_template"
    assert by_metric["humanApprovalRate"].kind == "review_artifact_template"
    assert all(isinstance(s, Suggestion) for s in suggestions)
    assert all(s.target_agent_id == "agent-plan" for s in suggestions)


def test_metrics_trigger_overall_rules_fire():
    trigger = MetricsImprovementTrigger()
    overview = _overview(
        human={"approvalRate": 0.4},
        quality={"testPassRate": 0.5},
    )
    suggestions = trigger.assess(overview)
    kinds = {s.kind for s in suggestions}
    assert kinds == {"review_artifact_template", "strengthen_test_generation"}


def test_metrics_trigger_skips_missing_metrics():
    trigger = MetricsImprovementTrigger()
    assert trigger.assess(MetricsOverview()) == []
    assert trigger.assess(_overview(agents=[{"agentId": "agent-x"}])) == []
