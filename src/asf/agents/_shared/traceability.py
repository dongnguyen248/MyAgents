from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from asf.tools.changeset import ChangeSet

__all__ = ["build_metadata", "ArtifactKind"]


class ArtifactKind:
    CODE = "CODE"
    CODE_REVIEW = "CODE_REVIEW"
    TEST_REPORT = "TEST_REPORT"


def build_metadata(
    kind: str,
    *,
    task_item_id: str,
    generated_at: datetime,
    spec_id: str | None = None,
    plan_id: str | None = None,
    changeset: ChangeSet | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the metadata dict for CODE, CODE_REVIEW, or TEST_REPORT artifacts.

    Args:
        kind: One of "CODE", "CODE_REVIEW", "TEST_REPORT".
        task_item_id: The task item ID this artifact belongs to (e.g., "T1").
        generated_at: Timestamp from the agent's runtime clock (timezone-aware UTC).
        spec_id: Optional spec ID for traceability.
        plan_id: Optional plan ID for traceability.
        changeset: Optional ChangeSet (for CODE artifacts).
        extra: Optional extra fields to include.

    Returns:
        Metadata dictionary with required traceability fields.
    """
    if generated_at.tzinfo is None:
        raise ValueError("generated_at must be timezone-aware")
    if generated_at.tzinfo != UTC:
        generated_at = generated_at.astimezone(UTC)

    metadata: dict[str, Any] = {
        "artifactKind": kind,
        "taskItemId": task_item_id,
        "generatedAt": generated_at.isoformat(),
        "generatedBy": "agent",
    }

    if spec_id:
        metadata["specId"] = spec_id
    if plan_id:
        metadata["planId"] = plan_id

    if changeset is not None:
        metadata["filesChanged"] = sorted(fc.path for fc in changeset.changes)

    if extra:
        metadata.update(extra)

    return metadata
