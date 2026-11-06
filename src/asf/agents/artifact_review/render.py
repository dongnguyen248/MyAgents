"""Renderings of a validated artifact review.

Two surfaces: the markdown stored on the ARTIFACT_REVIEW artifact, and
the feedback text that goes back to the producing agent. Feedback is
grouped by severity with blockers first; truncation drops the lowest
severities first and never truncates a blocker.
"""

from __future__ import annotations

from asf.agents.artifact_review.prompts import ArtifactReviewContent, Finding, ReviewTarget

__all__ = ["FEEDBACK_MAX_CHARS", "render_feedback", "render_review_markdown"]

FEEDBACK_MAX_CHARS = 8_000
SEVERITY_ORDER = ("BLOCKER", "MAJOR", "MINOR", "NIT")
OPEN_STATUSES = ("NEW", "STILL_OPEN")


def render_review_markdown(
    content: ArtifactReviewContent, *, target: ReviewTarget, verdict: str
) -> str:
    """Render only validated data; metadata is injected by the agent."""
    artifact = target.artifact
    lines = [
        "# ARTIFACT_REVIEW",
        "",
        f"Stage: {target.stage}",
        f"Round: {target.round_number}",
        f"Reviewed artifact: {artifact.id} (version {artifact.version})",
        f"Verdict: {verdict}",
        "",
        content.summary,
        "",
    ]
    for finding in content.findings:
        lines.extend(_finding_lines(finding))
    return "\n".join(lines).strip()


def _finding_lines(finding: Finding) -> list[str]:
    lines = [
        f"## {finding.id} [{finding.severity}][{finding.category}] {finding.location}",
        "",
        f"Status: {finding.status} · Source: {finding.source}",
        "",
        finding.problem,
        "",
        f"Required change: {finding.required_change}",
        "",
    ]
    if finding.waiver_reason:
        lines.extend([f"Waiver reason: {finding.waiver_reason}", ""])
    return lines


def _feedback_line(finding: Finding) -> str:
    return (
        f"[{finding.id}][{finding.severity}][{finding.category}] "
        f"{finding.location}: {finding.problem} → {finding.required_change}"
    )


def _grouped(findings: list[Finding]) -> list[Finding]:
    ordered: list[Finding] = []
    for severity in SEVERITY_ORDER:
        ordered.extend(finding for finding in findings if finding.severity == severity)
    return ordered


def render_feedback(
    findings: list[Finding],
    regressions: list[str],
    *,
    max_chars: int = FEEDBACK_MAX_CHARS,
) -> str:
    """The findings text a producer agent receives for its revision.

    Only open findings are fed back. Lines are dropped lowest-severity
    first when the text would exceed ``max_chars``; BLOCKER lines are
    never dropped, even if they alone exceed the cap.
    """
    open_findings = [f for f in findings if f.status in OPEN_STATUSES]
    lines = [_feedback_line(finding) for finding in _grouped(open_findings)]
    header: list[str] = []
    if regressions:
        header.append(f"Previously resolved findings that are open again: {', '.join(regressions)}")
    kept, omitted = _truncate_lines(header, lines, max_chars)
    if omitted:
        kept.append(f"… ({omitted} lower-severity findings omitted; see the review artifact)")
    return "\n".join(header + kept)


def _truncate_lines(header: list[str], lines: list[str], max_chars: int) -> tuple[list[str], int]:
    kept = list(lines)
    omitted = 0
    while kept and len("\n".join(header + kept)) > max_chars:
        droppable = [i for i, line in enumerate(kept) if "[BLOCKER]" not in line]
        if not droppable:
            break
        kept.pop(droppable[-1])
        omitted += 1
    return kept, omitted
