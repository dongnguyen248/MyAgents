"""Tests for the offline evaluation harness (real agents, scripted model)."""

from pathlib import Path

from harness.evaluation.cases import BenchmarkCase, load_cases
from harness.evaluation.runner import EvaluationRunner

CASES_DIR = Path(__file__).resolve().parents[2] / "harness" / "evaluation" / "cases"


def test_cases_load_from_default_directory():
    cases = load_cases(CASES_DIR)
    assert len(cases) >= 3
    ids = [case.id for case in cases]
    assert ids == sorted(ids)
    for case in cases:
        assert case.expected_artifacts == ["SPEC", "PLAN"]
        assert case.requirement
        assert case.must_complete is True


def test_run_case_passes_end_to_end_with_real_agents():
    case = BenchmarkCase(
        id="smoke",
        requirement="Build a tiny greeting module with a greet(name) function.",
        expected_artifacts=["SPEC", "PLAN"],
        max_revisions=2,
        must_complete=True,
    )
    result = EvaluationRunner().run_case(case)
    assert result.passed, result.failures
    assert result.completed is True
    assert result.artifacts_produced == ["PLAN", "SPEC"]
    assert result.revisions <= case.max_revisions
    assert result.score == 1.0
    assert result.duration_seconds >= 0


def test_run_case_flags_missing_artifacts_and_incompletion():
    case = BenchmarkCase(
        id="impossible",
        requirement="Build a tiny greeting module.",
        expected_artifacts=["SPEC", "PLAN", "CODE"],
        max_revisions=2,
        must_complete=True,
    )
    result = EvaluationRunner().run_case(case)
    assert result.passed is False
    assert any("CODE" in failure for failure in result.failures)
    assert result.score < 1.0


def test_report_math():
    cases = load_cases(CASES_DIR)
    report = EvaluationRunner().run_all(cases)
    assert len(report.results) == len(cases)
    expected_mean = round(sum(r.score for r in report.results) / len(cases), 4)
    assert report.mean_score == expected_mean
    expected_rate = round(sum(1 for r in report.results if r.passed) / len(cases), 4)
    assert report.pass_rate == expected_rate
    assert report.pass_rate == 1.0
