"""The per-run AI review history view behind GET /runs/{id}/reviews.

Pure projection over the run's ARTIFACT_REVIEW artifacts: for
each gated stage, the rounds in order with the verdict the code
derived, the severity counts, the summary and the findings
(mapped to the dashboard's camelCase shape). A stage appears
once its first round has been persisted.
"""

from __future__ import annotations

from typing import Any

from asf.orchestrator.execution import WorkflowExecution

__all__ = ["run_reviews_view"]

_SEVERITIES = ("BLOCKER", "MAJOR", "MINOR", "NIT")


def _finding_view(finding: Any) -> dict[str, Any] | None:
    if not isinstance(finding, dict):
        return None
    return {
        "id": finding.get("id"),
        "severity": finding.get("severity"),
        "category": finding.get("category"),
        "location": finding.get("location"),
        "problem": finding.get("problem"),
        "requiredChange": finding.get("required_change"),
        "status": finding.get("status"),
        "source": finding.get("source"),
        "waiverReason": finding.get("waiver_reason"),
    }


def _round_view(artifact: Any) -> dict[str, Any]:
    review = artifact.content.get("review") if isinstance(artifact.content, dict) else None
    review = review if isinstance(review, dict) else {}
    findings = [
        view
        for view in (_finding_view(item) for item in review.get("findings", []))
        if view is not None
    ]
    counts = artifact.metadata.get("findingCounts")
    if not isinstance(counts, dict):
        counts = {
            severity: sum(1 for item in findings if item["severity"] == severity)
            for severity in _SEVERITIES
        }
    return {
        "round": artifact.metadata.get("round"),
        "verdict": artifact.metadata.get("verdict"),
        "reviewArtifactId": artifact.id,
        "reviewedArtifactId": artifact.metadata.get("reviewedArtifactId"),
        "reviewedArtifactVersion": artifact.metadata.get("reviewedArtifactVersion"),
        "counts": counts,
        "summary": review.get("summary"),
        "findings": findings,
    }


def run_reviews_view(run: WorkflowExecution) -> dict[str, Any]:
    """The run's AI review rounds, grouped by stage in round order."""
    stages: dict[str, dict[str, Any]] = {}
    for artifact in run.artifact_history.values():
        if artifact.type != "ARTIFACT_REVIEW":
            continue
        stage = artifact.metadata.get("stage")
        if not isinstance(stage, str):
            continue
        entry = stages.setdefault(
            stage,
            {"stage": stage, "stepId": artifact.metadata.get("stepId") or stage, "rounds": []},
        )
        entry["rounds"].append(_round_view(artifact))
    for entry in stages.values():
        entry["rounds"].sort(key=lambda item: item["round"] or 0)
    return {"runId": run.id, "stages": list(stages.values())}
