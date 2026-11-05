from __future__ import annotations

from asf.agents._shared.contracts import (
    Finding,
    FindingSeverity,
    ReportContent,
    ReviewContent,
)
from asf.tools.ports import CommandResult


def test_finding_create() -> None:
    f = Finding(
        id="f1",
        severity=FindingSeverity.MAJOR,
        file="src/foo.py",
        line=10,
        message="Unused variable",
        rule_id="R001",
        suggestion="Remove it",
    )
    assert f.id == "f1"
    assert f.severity == FindingSeverity.MAJOR
    assert f.file == "src/foo.py"
    assert f.line == 10
    assert f.message == "Unused variable"
    assert f.rule_id == "R001"
    assert f.suggestion == "Remove it"


def test_finding_without_optional() -> None:
    f = Finding(
        id="f1",
        severity=FindingSeverity.INFO,
        file="src/foo.py",
        line=10,
        message="Info message",
    )
    assert f.rule_id is None
    assert f.suggestion is None


def test_finding_severity_enum() -> None:
    assert FindingSeverity.CRITICAL == "CRITICAL"
    assert FindingSeverity.MAJOR == "MAJOR"
    assert FindingSeverity.MINOR == "MINOR"
    assert FindingSeverity.INFO == "INFO"


def test_review_content() -> None:
    findings = (
        Finding(id="f1", severity=FindingSeverity.MAJOR, file="a.py", line=1, message="msg"),
    )
    rc = ReviewContent(findings=findings, summary="Review summary", approved=False)
    assert len(rc.findings) == 1
    assert rc.summary == "Review summary"
    assert rc.approved is False


def test_review_content_approved() -> None:
    rc = ReviewContent(findings=(), summary="All good", approved=True)
    assert rc.approved is True


def test_report_content() -> None:
    rc = ReportContent(
        passed=5,
        failed=1,
        skipped=0,
        duration_ms=1000,
        details={"test_a": "passed", "test_b": "failed"},
    )
    assert rc.passed == 5
    assert rc.failed == 1
    assert rc.skipped == 0
    assert rc.duration_ms == 1000
    assert rc.details["test_a"] == "passed"


def test_command_result() -> None:
    cr = CommandResult(
        exit_code=0,
        stdout="output",
        stderr="",
        duration_ms=100,
        timed_out=False,
    )
    assert cr.exit_code == 0
    assert cr.stdout == "output"
    assert cr.timed_out is False


def test_command_result_timed_out() -> None:
    cr = CommandResult(
        exit_code=1,
        stdout="out",
        stderr="err",
        duration_ms=200,
        timed_out=True,
    )
    assert cr.exit_code == 1
    assert cr.stdout == "out"
    assert cr.stderr == "err"
    assert cr.duration_ms == 200
    assert cr.timed_out is True
