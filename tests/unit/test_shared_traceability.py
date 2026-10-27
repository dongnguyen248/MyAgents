from __future__ import annotations

from datetime import datetime, timezone

from asf.agents._shared.traceability import ArtifactKind, build_metadata
from asf.tools.changeset import ChangeSet, FileChange


def test_build_metadata_code_artifact() -> None:
    changeset = ChangeSet(changes=(
        FileChange(path="src/a.py", operation="create", content="a"),
        FileChange(path="src/b.py", operation="modify", content="b"),
    ))
    metadata = build_metadata(
        ArtifactKind.CODE,
        task_id="task-123",
        generated_at=datetime.now(timezone.utc),
        spec_id="spec-456",
        plan_id="plan-789",
        changeset=changeset,
    )
    assert metadata["artifactKind"] == "CODE"
    assert metadata["taskId"] == "task-123"
    assert metadata["specId"] == "spec-456"
    assert metadata["planId"] == "plan-789"
    assert metadata["filesChanged"] == ["src/a.py", "src/b.py"]
    assert metadata["generatedBy"] == "agent"
    assert "generatedAt" in metadata


def test_build_metadata_code_review_artifact() -> None:
    metadata = build_metadata(
        ArtifactKind.CODE_REVIEW,
        task_id="task-123",
        generated_at=datetime.now(timezone.utc),
        spec_id="spec-456",
        plan_id="plan-789",
    )
    assert metadata["artifactKind"] == "CODE_REVIEW"
    assert metadata["taskId"] == "task-123"
    assert metadata["specId"] == "spec-456"
    assert metadata["planId"] == "plan-789"
    assert "filesChanged" not in metadata


def test_build_metadata_test_report_artifact() -> None:
    metadata = build_metadata(
        ArtifactKind.TEST_REPORT,
        task_id="task-123",
        generated_at=datetime.now(timezone.utc),
    )
    assert metadata["artifactKind"] == "TEST_REPORT"
    assert metadata["taskId"] == "task-123"
    assert "specId" not in metadata
    assert "planId" not in metadata


def test_build_metadata_extra_fields() -> None:
    metadata = build_metadata(
        ArtifactKind.CODE,
        task_id="task-123",
        generated_at=datetime.now(timezone.utc),
        extra={"custom": "value", "count": 5},
    )
    assert metadata["custom"] == "value"
    assert metadata["count"] == 5


def test_build_metadata_no_changeset() -> None:
    metadata = build_metadata(
        ArtifactKind.CODE,
        task_id="task-123",
        generated_at=datetime.now(timezone.utc),
    )
    assert "filesChanged" not in metadata


def test_build_metadata_timezone_conversion() -> None:
    # Test that non-UTC timezones are converted to UTC
    from datetime import timedelta
    tz_est = timezone(timedelta(hours=-5))
    generated_at = datetime(2024, 1, 15, 10, 30, 0, tzinfo=tz_est)
    metadata = build_metadata(
        ArtifactKind.CODE,
        task_id="task-123",
        generated_at=generated_at,
    )
    # Should be converted to UTC (15:30 UTC)
    assert metadata["generatedAt"] == "2024-01-15T15:30:00+00:00"


def test_build_metadata_naive_datetime_raises() -> None:
    # Naive datetime should raise
    import pytest
    with pytest.raises(ValueError, match="timezone-aware"):
        build_metadata(
            ArtifactKind.CODE,
            task_id="task-123",
            generated_at=datetime(2024, 1, 15, 10, 30, 0),  # naive
        )