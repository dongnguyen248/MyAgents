"""Phase 12: feedback rendering order, grouping and truncation."""

from __future__ import annotations

from asf.agents.artifact_review.prompts import Finding
from asf.agents.artifact_review.render import render_feedback


def finding(fid: str, severity: str, status: str = "NEW", problem: str = "broken") -> Finding:
    return Finding(
        id=fid,
        severity=severity,  # type: ignore[arg-type]
        category="TRACEABILITY",
        location="REQ-1",
        problem=problem,
        required_change="fix it",
        status=status,  # type: ignore[arg-type]
    )


def test_feedback_line_format_and_severity_grouping() -> None:
    findings = [
        finding("F-003", "NIT"),
        finding("F-001", "BLOCKER"),
        finding("F-002", "MAJOR"),
    ]
    text = render_feedback(findings, [])
    lines = text.splitlines()
    assert lines[0].startswith("[F-001][BLOCKER][TRACEABILITY] REQ-1: broken → fix it")
    assert lines[1].startswith("[F-002][MAJOR]")
    assert lines[2].startswith("[F-003][NIT]")


def test_feedback_includes_only_open_findings_and_regressions_first() -> None:
    findings = [finding("F-001", "MAJOR", "RESOLVED"), finding("F-002", "MAJOR", "STILL_OPEN")]
    text = render_feedback(findings, ["F-001"])
    assert text.splitlines()[0] == "Previously resolved findings that are open again: F-001"
    assert "F-002" in text
    assert text.count("MAJOR") == 1


def test_feedback_truncation_drops_lowest_severity_first() -> None:
    findings = [finding("F-001", "BLOCKER", problem="b" * 60)]
    findings += [finding(f"F-1{i:02d}", "NIT", problem="n" * 60) for i in range(10)]
    findings += [finding("F-200", "MINOR", problem="m" * 60)]
    text = render_feedback(findings, [], max_chars=300)
    assert "[F-001][BLOCKER]" in text
    assert "omitted" in text
    assert len(text) <= 300 + 200  # blockers and the omission note may exceed the cap


def test_feedback_never_truncates_blockers() -> None:
    findings = [finding(f"F-00{i}", "BLOCKER", problem="b" * 100) for i in range(1, 4)]
    text = render_feedback(findings, [], max_chars=50)
    for index in range(1, 4):
        assert f"[F-00{index}][BLOCKER]" in text
