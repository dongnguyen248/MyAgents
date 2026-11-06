from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from asf.tools.changeset import ChangeSet

__all__ = ["build_metadata", "ArtifactKind", "MetadataSpec"]


class ArtifactKind:
    CODE = "CODE"
    CODE_REVIEW = "CODE_REVIEW"
    TEST_REPORT = "TEST_REPORT"


@dataclass(frozen=True)
class MetadataSpec:
    """What an artifact's traceability metadata is built from.

    kind: one of "CODE", "CODE_REVIEW", "TEST_REPORT".
    generated_at: a timezone-aware timestamp from the agent's
    runtime clock. spec_id, plan_id and changeset are optional
    traceability inputs; extra fields are merged in last.
    """

    kind: str
    task_item_id: str
    generated_at: datetime
    spec_id: str | None = None
    plan_id: str | None = None
    changeset: ChangeSet | None = None
    extra: dict[str, Any] | None = None


def build_metadata(spec: MetadataSpec) -> dict[str, Any]:
    """Build the metadata dict for CODE, CODE_REVIEW, or TEST_REPORT artifacts."""
    generated_at = spec.generated_at
    if generated_at.tzinfo is None:
        raise ValueError("generated_at must be timezone-aware")
    if generated_at.tzinfo != UTC:
        generated_at = generated_at.astimezone(UTC)

    metadata: dict[str, Any] = {
        "artifactKind": spec.kind,
        "taskItemId": spec.task_item_id,
        "generatedAt": generated_at.isoformat(),
        "generatedBy": "agent",
    }

    if spec.spec_id:
        metadata["specId"] = spec.spec_id
    if spec.plan_id:
        metadata["planId"] = spec.plan_id

    if spec.changeset is not None:
        metadata["filesChanged"] = sorted(fc.path for fc in spec.changeset.changes)

    if spec.extra:
        metadata.update(spec.extra)

    return metadata
