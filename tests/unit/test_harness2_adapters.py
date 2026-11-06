"""Tests for trajectory rendering, evidence building, adapters and the demo (H2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from asf.contracts.models import ModelRequest, ModelResponse, ModelUsage
from harness.harness2.adapters import PlanTaskAdapter, SpecTaskAdapter
from harness.harness2.context import (
    EvidenceItem,
    LeakTripwireError,
    assert_source_allowed,
    build_evidence,
)
from harness.harness2.demo import SOLVER_MARKER, DemoOptions, HarnessAwareGateway, run_demo
from harness.harness2.surface import SYSTEM_PATH
from harness.harness2.trajectory import (
    MIN_OBSERVATION_CHARS,
    TrajectoryRecorder,
    render_trajectory,
)


def test_render_trajectory_grammar_and_truncation() -> None:
    recorder = TrajectoryRecorder()
    recorder.record_call(
        ModelRequest(messages=[{"role": "system", "content": "x" * 25_000}], model="m")
    )
    recorder.record_reply(
        ModelResponse(
            content="the reply",
            model="m",
            usage=ModelUsage(prompt_tokens=1, completion_tokens=1),
            finish_reason="stop",
            metadata={},
        )
    )
    recorder.record_error("agent", "LLM_INVALID_RESPONSE: bad")
    text = render_trajectory(recorder.events, obs_trunc=MIN_OBSERVATION_CHARS)
    assert "[ACTION] model call (model=m)" in text
    assert "[OBSERVATION] message/system:" in text
    assert "[TRUNCATED 15000 chars]" in text
    assert "[OBSERVATION] reply:" in text
    assert "[ERROR] agent: LLM_INVALID_RESPONSE: bad" in text


def test_render_trajectory_rejects_sub_floor_budget() -> None:
    with pytest.raises(ValueError, match="fabricate defects"):
        render_trajectory([], obs_trunc=MIN_OBSERVATION_CHARS - 1)


def test_evidence_rejects_score_markers() -> None:
    item = EvidenceItem(
        label="base0", trajectory="the reply said CHANGES_REQUESTED", delivered=False
    )
    with pytest.raises(LeakTripwireError):
        build_evidence("calculator", [item])


def test_evidence_truncation_is_explicit() -> None:
    item = EvidenceItem(label="base0", trajectory="y" * 25_000, delivered=True)
    bundle = build_evidence("calculator", [item], per_item_chars=MIN_OBSERVATION_CHARS)
    assert bundle.truncated == ("base0",)
    assert "[TRUNCATED 15000 chars]" in bundle.entries[0].trajectory


def test_evidence_rejects_sub_floor_budget() -> None:
    with pytest.raises(ValueError):
        build_evidence("calculator", [], per_item_chars=MIN_OBSERVATION_CHARS - 1)


def test_rubric_paths_are_not_evidence_sources() -> None:
    with pytest.raises(LeakTripwireError):
        assert_source_allowed(Path("harness/evaluation/rubrics/spec.md"))
    assert_source_allowed(Path("harness/evaluation/cases/calculator.json"))


def _marked_tree(adapter) -> dict:
    tree = adapter.base_harness()
    tree[SYSTEM_PATH] = tree[SYSTEM_PATH] + f"\n{SOLVER_MARKER}\n"
    adapter.validate_tree(tree)
    return tree


def test_spec_adapter_tasks_domain_and_validation(tmp_path: Path) -> None:
    adapter = SpecTaskAdapter(runs_root=tmp_path)
    assert adapter.tasks() == ["calculator", "invoice-service", "todo-api"]
    assert adapter.domain_of("calculator") == "python"
    tree = adapter.base_harness()
    tree["prompts/contract.md"] += "edited"
    with pytest.raises(ValueError):
        adapter.validate_tree(tree)


def test_spec_adapter_scripted_rollout_delivers(tmp_path: Path) -> None:
    adapter = SpecTaskAdapter(runs_root=tmp_path)
    run_dir = adapter.execute("calculator", None, run_id="calculator-base-0")
    assert adapter.delivered(run_dir)
    assert "SPEC" in adapter.deliverable_text(run_dir)
    assert adapter.score(run_dir, "calculator") == {"delivered": True, "completion": 1.0}


def test_spec_adapter_is_harness_sensitive_with_aware_gateway(tmp_path: Path) -> None:
    adapter = SpecTaskAdapter(runs_root=tmp_path, gateway_factory=HarnessAwareGateway)
    base_dir = adapter.execute("calculator", None, run_id="calculator-base-0")
    assert not adapter.delivered(base_dir)
    marked_dir = adapter.execute("calculator", _marked_tree(adapter), run_id="calculator-inv0")
    assert adapter.delivered(marked_dir)
    trajectory = adapter.trajectory(marked_dir, obs_trunc=MIN_OBSERVATION_CHARS)
    assert "[ACTION]" in trajectory
    assert SOLVER_MARKER in trajectory


def test_plan_adapter_is_harness_sensitive_with_aware_gateway(tmp_path: Path) -> None:
    adapter = PlanTaskAdapter(runs_root=tmp_path, gateway_factory=HarnessAwareGateway)
    base_dir = adapter.execute("calculator", None, run_id="calculator-base-0")
    assert not adapter.delivered(base_dir)
    marked_dir = adapter.execute("calculator", _marked_tree(adapter), run_id="calculator-inv0")
    assert adapter.delivered(marked_dir)


def test_execute_is_idempotent_by_run_id(tmp_path: Path) -> None:
    calls = {"count": 0}

    class CountingGateway(HarnessAwareGateway):
        def complete(self, request):  # type: ignore[override]
            calls["count"] += 1
            return super().complete(request)

    adapter = SpecTaskAdapter(runs_root=tmp_path, gateway_factory=CountingGateway)
    first = adapter.execute("calculator", None, run_id="calculator-base-0")
    second = adapter.execute("calculator", None, run_id="calculator-base-0")
    assert first == second
    assert calls["count"] == 1


@pytest.mark.parametrize("mode", ["parallel", "sequential"])
def test_demo_adopts_the_marker_edit(tmp_path: Path, mode: str) -> None:
    result = run_demo(DemoOptions(mode=mode, k=2, runs_root=tmp_path))
    assert len(result.run.ledger.rollouts) == 8
    assert len(result.run.ledger.sessions) == 6
    assert result.adopted is not None
    assert any(SYSTEM_PATH in line for line in result.adopted_diff)
    assert SOLVER_MARKER in result.adopted.tree[SYSTEM_PATH]
