"""Phase 12: deterministic mechanical checks per stage."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from asf.agents.artifact_review.checks import (
    PLAN_SECTIONS,
    SPEC_SECTIONS,
    run_mechanical_checks,
    split_sections,
)
from asf.contracts.models import Artifact

NOW = datetime(2026, 1, 1, tzinfo=UTC)
REPO_ROOT = Path(__file__).resolve().parents[2]

GOOD_SPEC = """# SPEC: Demo

## Background / Goal
Build a calculator.

## Scope (in / out)
In: arithmetic. Out: graphing.

## Functional requirements
- REQ-1: Add two numbers.
- REQ-2: Reject division by zero.

## Non-functional requirements
- Standard library only.

## Acceptance criteria
- REQ-1: add(1, 2) returns 3.
- REQ-2: divide(1, 0) raises a clear error.

## Open questions
None.

## Revision history
- v1: initial.
"""

GOOD_PLAN = """# PLAN: Demo

## Linked SPEC
SPEC spec-1 version 1.

## Scope and out of scope
In: arithmetic. Out: graphing.

## Approach / architecture
One module implementing REQ-1 and REQ-2.

## Impacted components
calculator.py only.

## Milestones
### M1: Core
- Deliverables: calculator module covering REQ-1 and REQ-2.
- Acceptance criteria: tests pass.
- Depends on: none

## Testing strategy
Unit tests for every requirement.

## Risks & mitigations
None known.

## Open questions
None.

## Revision history
- v1: initial.
"""


def artifact(kind: str, content: Any, artifact_id: str = "x-1") -> Artifact:
    return Artifact(
        id=artifact_id,
        type=kind,
        name=f"{kind}.md",
        version="1",
        content=content,
        created_by="agent-x",
        created_at=NOW,
        metadata={},
    )


def spec_artifact(text: str = GOOD_SPEC) -> Artifact:
    return artifact("SPEC", {"format": "markdown", "text": text}, "spec-1")


def plan_artifact(text: str = GOOD_PLAN) -> Artifact:
    return artifact("PLAN", {"format": "markdown", "text": text}, "plan-1")


def task_item(**overrides: Any) -> dict[str, Any]:
    item = {
        "id": "T1",
        "title": "Implement REQ-1 addition",
        "milestoneRef": "M1",
        "description": "Implement the add function for REQ-1; run unit tests.",
        "acceptanceCriteria": ["REQ-1: add(1, 2) == 3"],
        "dependsOn": [],
        "expectedFiles": ["calculator.py"],
        "verificationHint": "Run the unit tests",
    }
    item.update(overrides)
    return item


def severities(findings: list) -> list[tuple[str, str]]:
    return [(finding.severity, finding.location) for finding in findings]


def test_section_lists_match_the_shipped_templates() -> None:
    spec_template = (REPO_ROOT / "templates" / "spec" / "SPEC.md").read_text(encoding="utf-8")
    plan_template = (REPO_ROOT / "templates" / "plan" / "PLAN.md").read_text(encoding="utf-8")
    assert tuple(split_sections(spec_template)) == SPEC_SECTIONS
    assert tuple(split_sections(plan_template)) == PLAN_SECTIONS


def test_good_spec_and_plan_have_no_findings() -> None:
    assert run_mechanical_checks("spec", spec_artifact(), {}) == []
    upstream = {"SPEC": spec_artifact()}
    assert run_mechanical_checks("plan", plan_artifact(), upstream) == []


def test_spec_missing_and_empty_sections_block() -> None:
    text = GOOD_SPEC.replace("## Open questions\nNone.\n", "")
    findings = run_mechanical_checks("spec", spec_artifact(text), {})
    assert ("BLOCKER", "## Open questions") in severities(findings)
    text = GOOD_SPEC.replace("Build a calculator.", "")
    findings = run_mechanical_checks("spec", spec_artifact(text), {})
    assert ("BLOCKER", "## Background / Goal") in severities(findings)


def test_spec_requirement_id_rules() -> None:
    no_ids = GOOD_SPEC.replace(
        "- REQ-1: Add two numbers.\n- REQ-2: Reject division by zero.", "- Add."
    )
    findings = run_mechanical_checks("spec", spec_artifact(no_ids), {})
    assert any(f.category == "COMPLETENESS" for f in findings)
    duplicated = GOOD_SPEC.replace("- REQ-2: Reject division by zero.", "- REQ-1: Again.")
    findings = run_mechanical_checks("spec", spec_artifact(duplicated), {})
    assert ("BLOCKER", "REQ-1") in severities(findings)
    assert any(f.category == "CONSISTENCY" for f in findings)


def test_spec_requirement_without_acceptance_criterion_blocks() -> None:
    text = GOOD_SPEC.replace("- REQ-2: divide(1, 0) raises a clear error.\n", "")
    findings = run_mechanical_checks("spec", spec_artifact(text), {})
    assert ("BLOCKER", "REQ-2") in severities(findings)
    assert any(f.category == "TRACEABILITY" for f in findings)


def test_common_empty_and_truncated_artifacts_block() -> None:
    findings = run_mechanical_checks("spec", spec_artifact("   "), {})
    assert findings and findings[0].severity == "BLOCKER"
    fenced = GOOD_SPEC + "\n```python\ndef broken(:\n"
    findings = run_mechanical_checks("spec", spec_artifact(fenced), {})
    assert any("code fence" in f.problem for f in findings)
    table = GOOD_SPEC + "\n| a | b\n"
    findings = run_mechanical_checks("spec", spec_artifact(table), {})
    assert any("mid-table" in f.problem for f in findings)


def test_plan_coverage_and_unknown_references() -> None:
    upstream = {"SPEC": spec_artifact()}
    missing = GOOD_PLAN.replace("implementing REQ-1 and REQ-2", "implementing REQ-1")
    missing = missing.replace("covering REQ-1 and REQ-2", "covering REQ-1")
    findings = run_mechanical_checks("plan", plan_artifact(missing), upstream)
    assert ("BLOCKER", "REQ-2") in severities(findings)
    unknown = GOOD_PLAN.replace("REQ-1 and REQ-2", "REQ-1 and REQ-9")
    findings = run_mechanical_checks("plan", plan_artifact(unknown), upstream)
    assert ("BLOCKER", "REQ-9") in severities(findings)
    assert all(f.source == "mechanical" for f in findings)


def good_tasks() -> Artifact:
    tasks = [
        task_item(),
        task_item(
            id="T2",
            title="Implement REQ-2 guard",
            description="Reject division by zero for REQ-2; run unit tests.",
            acceptanceCriteria=["REQ-2: divide(1, 0) raises"],
            dependsOn=["T1"],
        ),
    ]
    return artifact("TASK", {"format": "json", "tasks": tasks}, "task-1")


def test_good_task_breakdown_has_no_findings() -> None:
    upstream = {"SPEC": spec_artifact(), "PLAN": plan_artifact()}
    assert run_mechanical_checks("task", good_tasks(), upstream) == []


def test_task_shape_problems_block() -> None:
    upstream = {"SPEC": spec_artifact()}
    broken = artifact("TASK", {"format": "json", "tasks": "nope"}, "task-1")
    findings = run_mechanical_checks("task", broken, upstream)
    assert findings and findings[0].severity == "BLOCKER"
    missing_title = artifact("TASK", {"tasks": [task_item(title="")]}, "task-1")
    findings = run_mechanical_checks("task", missing_title, upstream)
    assert ("BLOCKER", "T1") in severities(findings)
    duplicated = artifact("TASK", {"tasks": [task_item(), task_item()]}, "task-1")
    findings = run_mechanical_checks("task", duplicated, upstream)
    assert any(f.category == "CONSISTENCY" for f in findings)


def test_task_dependency_graph_problems() -> None:
    upstream = {"SPEC": spec_artifact()}
    unknown = artifact("TASK", {"tasks": [task_item(dependsOn=["T9"])]}, "task-1")
    findings = run_mechanical_checks("task", unknown, upstream)
    assert any("unknown task T9" in f.problem for f in findings)
    self_dep = artifact("TASK", {"tasks": [task_item(dependsOn=["T1"])]}, "task-1")
    findings = run_mechanical_checks("task", self_dep, upstream)
    assert any("depends on itself" in f.problem for f in findings)
    cycle = artifact(
        "TASK",
        {"tasks": [task_item(dependsOn=["T2"]), task_item(id="T2", dependsOn=["T1"])]},
        "task-1",
    )
    findings = run_mechanical_checks("task", cycle, upstream)
    cycle_findings = [f for f in findings if "cycle" in f.problem]
    assert cycle_findings and "T1 -> T2 -> T1" in cycle_findings[0].problem


def test_task_coverage_paths_cap_and_test_minor() -> None:
    upstream = {"SPEC": spec_artifact()}
    uncovered = artifact("TASK", {"tasks": [task_item()]}, "task-1")
    findings = run_mechanical_checks("task", uncovered, upstream)
    assert ("BLOCKER", "REQ-2") in severities(findings)
    bad_path = artifact("TASK", {"tasks": [task_item(expectedFiles=["../secret.py"])]}, "task-1")
    findings = run_mechanical_checks("task", bad_path, upstream)
    assert any(f.category == "RISK" for f in findings)
    absolute = artifact("TASK", {"tasks": [task_item(expectedFiles=["/etc/x.py"])]}, "task-1")
    findings = run_mechanical_checks("task", absolute, upstream)
    assert any(f.category == "RISK" for f in findings)
    many = artifact("TASK", {"tasks": [task_item(id=f"T{i}") for i in range(1, 4)]}, "task-1")
    findings = run_mechanical_checks("task", many, upstream, max_tasks=2)
    assert any(f.category == "SCOPE" for f in findings)
    no_test = task_item(
        description="Implement the add function for REQ-1.",
        verificationHint="Check the module imports",
        acceptanceCriteria=["REQ-1 works"],
    )
    findings = run_mechanical_checks("task", artifact("TASK", {"tasks": [no_test]}, "task-1"), {})
    assert ("MINOR", "T1") in severities(findings)
