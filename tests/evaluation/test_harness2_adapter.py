"""Tests for the Harness² adapter seam (null default + local rules)."""

from harness.harness2 import (
    LocalHarness2Adapter,
    NullHarness2Adapter,
    Suggestion,
    default_adapter,
)


def _overview(**overrides):
    overview = {
        "agents": [],
        "human": {"approvalRate": 0.9},
        "quality": {"testPassRate": 0.95},
    }
    overview.update(overrides)
    return overview


def test_null_adapter_is_default_and_suggests_nothing():
    adapter = default_adapter()
    assert isinstance(adapter, NullHarness2Adapter)
    assert adapter.available is False
    assert adapter.assess(_overview()) == []
    assert adapter.assess({}) == []


def test_local_adapter_quiet_on_healthy_overview():
    adapter = LocalHarness2Adapter()
    assert adapter.available is True
    overview = _overview(agents=[{
        "agentId": "agent-spec", "successRate": 0.99, "avgRevisions": 0.4,
        "humanApprovalRate": 0.95, "healthScore": 92,
    }])
    assert adapter.assess(overview) == []


def test_local_adapter_agent_rules_fire():
    adapter = LocalHarness2Adapter()
    overview = _overview(agents=[{
        "agentId": "agent-plan", "successRate": 0.6, "avgRevisions": 2.3,
        "humanApprovalRate": 0.3, "healthScore": 55,
    }])
    suggestions = adapter.assess(overview)
    by_metric = {s.metric: s for s in suggestions}
    assert set(by_metric) == {"healthScore", "avgRevisions", "humanApprovalRate"}
    assert by_metric["healthScore"].kind == "investigate_agent"
    assert by_metric["healthScore"].value == 55
    assert by_metric["avgRevisions"].kind == "tighten_prompt_or_template"
    assert by_metric["humanApprovalRate"].kind == "review_artifact_template"
    assert all(isinstance(s, Suggestion) for s in suggestions)
    assert all(s.target_agent_id == "agent-plan" for s in suggestions)


def test_local_adapter_overall_rules_fire():
    adapter = LocalHarness2Adapter()
    overview = _overview(
        human={"approvalRate": 0.4},
        quality={"testPassRate": 0.5},
    )
    suggestions = adapter.assess(overview)
    kinds = {s.kind for s in suggestions}
    assert kinds == {"review_artifact_template", "strengthen_test_generation"}


def test_local_adapter_skips_missing_metrics():
    adapter = LocalHarness2Adapter()
    assert adapter.assess({}) == []
    assert adapter.assess({"agents": [{"agentId": "agent-x"}]}) == []
