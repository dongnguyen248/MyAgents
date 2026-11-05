from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from asf.tools.ports import CommandResult

__all__ = [
    "Finding",
    "FindingSeverity",
    "ReviewContent",
    "ReportContent",
    "CommandResult",
]


class FindingSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"
    INFO = "INFO"


@dataclass(frozen=True)
class Finding:
    """A single finding in a code review."""

    id: str
    severity: FindingSeverity
    file: str
    line: int
    message: str
    rule_id: str | None = None
    suggestion: str | None = None


@dataclass(frozen=True)
class ReviewContent:
    """Content of a CODE_REVIEW artifact."""

    findings: tuple[Finding, ...]
    summary: str
    approved: bool


@dataclass(frozen=True)
class ReportContent:
    """Content of a TEST_REPORT artifact."""

    passed: int
    failed: int
    skipped: int
    duration_ms: int
    details: dict[str, Any]
