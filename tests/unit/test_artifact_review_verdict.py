"""Phase 12: verdict derivation, carry-forward, stagnation, regression."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from asf.agents.artifact_review.prompts import ArtifactReviewContent, Finding
from asf.agents.artifact_review.verdict import (
    RoundOutcome,
    carry_forward_findings,
    derive_verdict,
    detect_regression,
    detect_stagnation,
    merge_findings,
    open_blocking,
)


def finding(
    fid: str,
    severity: str = "MAJOR",
    status: str = "NEW",
    source: str = "ai",
) -> Finding:
    return Finding(
        id=fid,
        severity=severity,  # type: ignore[arg-type]
        category="TRACEABILITY",
        location="REQ-1",
        problem="a concrete problem",
        required_change="a concrete change",
        status=status,  # type: ignore[arg-type]
        waiver_reason="accepted risk" if status == "WAIVED" else None,
        source=source,  # type: ignore[arg-type]
    )


def test_derive_verdict_approves_with_no_open_blocking() -> None:
    assert derive_verdict([]) == "APPROVE"
    assert derive_verdict([finding("F-001", "MINOR")]) == "APPROVE"
    assert derive_verdict([finding("F-001", "BLOCKER", "RESOLVED")]) == "APPROVE"


def test_derive_verdict_blocks_on_open_blocker_and_major() -> None:
    assert derive_verdict([finding("F-001", "BLOCKER")]) == "REQUEST_CHANGES"
    assert derive_verdict([finding("F-001", "MAJOR", "STILL_OPEN")]) == "REQUEST_CHANGES"


def test_derive_verdict_honours_custom_block_on() -> None:
    minor = finding("F-001", "MINOR")
    assert derive_verdict([minor], ("BLOCKER", "MAJOR", "MINOR")) == "REQUEST_CHANGES"
    assert derive_verdict([minor], ("BLOCKER",)) == "APPROVE"


def test_bias_guard_round_two_new_minor_cannot_block() -> None:
    minor = finding("F-009", "MINOR", "NEW")
    block_on = ("BLOCKER", "MAJOR", "MINOR")
    assert derive_verdict([minor], block_on, round_number=1) == "REQUEST_CHANGES"
    assert derive_verdict([minor], block_on, round_number=2) == "APPROVE"
    still_open = finding("F-001", "MINOR", "STILL_OPEN")
    assert derive_verdict([still_open], block_on, round_number=2) == "REQUEST_CHANGES"
    mechanical = finding("M-001", "MINOR", "NEW", source="mechanical")
    assert derive_verdict([mechanical], block_on, round_number=2) == "REQUEST_CHANGES"


def test_carry_forward_readds_unmentioned_open_findings() -> None:
    previous = [finding("F-001", "MAJOR", "NEW"), finding("F-002", "MINOR", "RESOLVED")]
    current = [finding("F-003", "NIT")]
    merged = carry_forward_findings(previous, current)
    assert [item.id for item in merged] == ["F-003", "F-001"]
    assert merged[1].status == "STILL_OPEN"


def test_carry_forward_keeps_mentioned_and_closed_findings_closed() -> None:
    previous = [finding("F-001", "MAJOR", "STILL_OPEN"), finding("F-002", "MAJOR", "WAIVED")]
    current = [finding("F-001", "MAJOR", "RESOLVED")]
    merged = carry_forward_findings(previous, current)
    assert [item.id for item in merged] == ["F-001"]
    assert merged[0].status == "RESOLVED"


def test_detect_regression_finds_resolved_then_open() -> None:
    previous = [finding("F-001", "MAJOR", "RESOLVED"), finding("F-002", "MAJOR", "STILL_OPEN")]
    current = [finding("F-001", "MAJOR", "STILL_OPEN"), finding("F-002", "MAJOR", "RESOLVED")]
    assert detect_regression(previous, current) == ["F-001"]


def _outcome(findings: list[Finding], artifact_hash: str, change_ratio: float) -> RoundOutcome:
    return RoundOutcome(
        findings=tuple(findings), artifact_hash=artifact_hash, change_ratio=change_ratio
    )


def test_stagnation_identical_artifact() -> None:
    previous = _outcome([finding("F-001", "BLOCKER")], "hash-a", 0.5)
    current = _outcome([finding("F-001", "BLOCKER")], "hash-a", 0.0)
    assert detect_stagnation(previous, current) is True


def test_stagnation_same_blocking_set_and_barely_changed() -> None:
    previous = _outcome([finding("F-001", "BLOCKER")], "hash-a", 0.0)
    current = _outcome([finding("F-001", "BLOCKER", "STILL_OPEN")], "hash-b", 0.01)
    assert detect_stagnation(previous, current) is True


def test_stagnation_trivial_edit_same_blockers_still_open() -> None:
    # A large content change alone is not progress: every blocker from
    # the previous round is still open, so the round stagnated.
    previous = _outcome([finding("F-001", "BLOCKER")], "hash-a", 0.0)
    current = _outcome([finding("F-001", "BLOCKER", "STILL_OPEN")], "hash-b", 0.9)
    assert detect_stagnation(previous, current) is True


def test_no_stagnation_when_the_blocking_set_shrank() -> None:
    previous = _outcome([finding("F-001", "BLOCKER"), finding("F-002", "MAJOR")], "hash-a", 0.0)
    shrank = _outcome([finding("F-002", "MAJOR", "STILL_OPEN")], "hash-b", 0.01)
    assert detect_stagnation(previous, shrank) is False
    replaced = _outcome([finding("F-002", "BLOCKER")], "hash-b", 0.01)
    assert detect_stagnation(previous, replaced) is False
    cleared = _outcome([], "hash-b", 0.01)
    assert detect_stagnation(previous, cleared) is False


def test_merge_findings_soft_matches_a_renumbered_finding() -> None:
    previous = [finding("F-001", "BLOCKER", "STILL_OPEN")]
    renumbered = finding("F-007", "BLOCKER", "NEW")
    merged = merge_findings(previous, [renumbered])
    assert [item.id for item in merged] == ["F-001"]
    assert merged[0].status == "STILL_OPEN"
    # The blocking count is not inflated by the renumbering, and the
    # unresolved blocker is not hidden either.
    assert len(open_blocking(merged, ("BLOCKER", "MAJOR"))) == 1
    assert derive_verdict(merged) == "REQUEST_CHANGES"


def test_merge_findings_soft_match_uses_category_and_normalized_location() -> None:
    previous = [finding("F-001", "MAJOR", "STILL_OPEN")]
    moved = Finding(
        id="F-009",
        severity="MAJOR",
        category="CLARITY",
        location="REQ-1",
        problem="same place, different category",
        required_change="a concrete change",
        status="NEW",
    )
    merged = merge_findings(previous, [moved])
    # Different category: not the same finding, so the old one is
    # carried forward alongside the new one.
    assert [item.id for item in merged] == ["F-009", "F-001"]


def test_merge_findings_still_carries_forward_unmatched_findings() -> None:
    previous = [
        finding("F-001", "BLOCKER", "STILL_OPEN"),
        finding("F-002", "MAJOR", "RESOLVED"),
    ]
    unrelated = Finding(
        id="F-003",
        severity="MINOR",
        category="TRACEABILITY",
        location="REQ-9",
        problem="a different place entirely",
        required_change="a concrete change",
        status="NEW",
    )
    merged = merge_findings(previous, [unrelated])
    assert [item.id for item in merged] == ["F-003", "F-001"]
    assert merged[1].status == "STILL_OPEN"


def test_content_validation_waived_rules() -> None:
    with pytest.raises(ValidationError):
        Finding(
            id="F-001",
            severity="MINOR",
            category="CLARITY",
            location="x",
            problem="p",
            required_change="c",
            status="WAIVED",
        )
    with pytest.raises(ValidationError):
        Finding(
            id="F-001",
            severity="BLOCKER",
            category="CLARITY",
            location="x",
            problem="p",
            required_change="c",
            status="WAIVED",
            waiver_reason="accepted",
        )


def test_content_rejects_model_supplied_verdict_and_overflow() -> None:
    with pytest.raises(ValidationError):
        ArtifactReviewContent.model_validate(
            {"findings": [], "summary": "ok", "verdict": "APPROVE"}
        )
    too_many = [finding(f"F-{index:03d}").model_dump() for index in range(21)]
    with pytest.raises(ValidationError):
        ArtifactReviewContent.model_validate({"findings": too_many, "summary": "ok"})
    with pytest.raises(ValidationError):
        ArtifactReviewContent.model_validate({"findings": [], "summary": "x" * 601})
