"""Tests for the fix-cycle optimization experiment (real orchestrator runs)."""

from harness.optimization.experiments import run_fix_cycle_experiment


def test_experiment_compares_both_configs_and_declares_winner():
    experiment = run_fix_cycle_experiment()
    assert len(experiment.results) == 2
    by_config = {r.config: r for r in experiment.results}
    assert set(by_config) == {"max_fixes=0", "max_fixes=3"}

    zero = by_config["max_fixes=0"]
    assert zero.completed is False
    assert zero.final_stage == "CODE_FIX_ESCALATED"
    assert zero.fix_cycles_used == 0

    three = by_config["max_fixes=3"]
    assert three.completed is True
    assert three.final_stage == "COMPLETED"
    assert three.fix_cycles_used == 1
    assert three.score > zero.score

    assert experiment.winner == "max_fixes=3"
    assert experiment.rationale
