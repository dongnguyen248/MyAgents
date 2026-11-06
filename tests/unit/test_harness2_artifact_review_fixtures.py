"""The artifact-review offline fixtures stay true to their labels.

Data-only fixtures (Phase 12, Stage E): this test is the only thing
that reads them today. It proves the manifest is complete and that
every fixture labelled `mechanical` really trips the deterministic
checks with a BLOCKER in the expected category, while the judgement
fixtures pass the mechanical checks (their defect needs the model).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from asf.agents.artifact_review.checks import run_mechanical_checks
from asf.contracts.models import Artifact

FIXTURES = Path(__file__).resolve().parents[2] / "harness/harness2/fixtures/artifact-review"
NOW = datetime(2026, 11, 6, tzinfo=UTC)
STAGES = ("spec", "plan", "task")
CANONICAL_LABELS = {
    "good",
    "missing-section",
    "broken-traceability",
    "cyclic-tasks",
    "vague-acceptance-criteria",
    "scope-creep",
}


def _manifest() -> dict[str, Any]:
    return json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))


def _artifact(stage: str, relative: str, kind: str) -> Artifact:
    path = FIXTURES / relative
    if stage == "task" and kind == "TASK":
        envelope = json.loads(path.read_text(encoding="utf-8"))
        content: dict[str, Any] = {"format": "json", "tasks": envelope["tasks"]}
    else:
        content = {"format": "markdown", "text": path.read_text(encoding="utf-8")}
    return Artifact(
        id=f"fixture-{path.stem}",
        type=kind,
        name=path.name,
        version="1",
        content=content,
        created_by="fixture",
        created_at=NOW,
        metadata={},
    )


def _run(fixture: dict[str, Any]) -> list[Any]:
    stage = fixture["stage"]
    artifact = _artifact(stage, fixture["artifact"], stage.upper())
    upstream = {
        kind: _artifact(stage, relative, kind) for kind, relative in fixture["upstream"].items()
    }
    return run_mechanical_checks(stage, artifact, upstream)


def test_manifest_covers_every_stage_and_label() -> None:
    fixtures = _manifest()["fixtures"]
    for stage in STAGES:
        stage_fixtures = [item for item in fixtures if item["stage"] == stage]
        assert len(stage_fixtures) >= 6, stage
        assert any(item["label"] == "good" for item in stage_fixtures), stage
    labels = {item["label"] for item in fixtures}
    assert labels >= CANONICAL_LABELS
    task_labels = {item["label"] for item in fixtures if item["stage"] == "task"}
    assert "cyclic-tasks" in task_labels


def test_mechanical_fixtures_trip_a_blocker_in_the_expected_category() -> None:
    for fixture in _manifest()["fixtures"]:
        if not fixture["expected"]["mechanical"]:
            continue
        findings = _run(fixture)
        blockers = [finding for finding in findings if finding.severity == "BLOCKER"]
        assert blockers, fixture["id"]
        categories = {finding.category for finding in findings}
        assert set(fixture["expected"]["categories"]) <= categories, fixture["id"]


def test_non_mechanical_fixtures_pass_the_mechanical_checks() -> None:
    for fixture in _manifest()["fixtures"]:
        if fixture["expected"]["mechanical"]:
            continue
        findings = _run(fixture)
        blockers = [finding for finding in findings if finding.severity == "BLOCKER"]
        assert not blockers, (fixture["id"], blockers)
