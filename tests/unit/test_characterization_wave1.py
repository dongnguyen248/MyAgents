"""Characterization tests for the Wave 1 refactor scope.

These pin the CURRENT behaviour of two pure shared functions —
``check_code_request`` (agents/_shared/code_agents.py) and
``parse_milestones`` (agents/plan/milestones.py) — input to output,
including every rejection reason, so the behavior-preserving
refactor of the agents tree can prove nothing changed. They were
written from the functions' actual outputs, not from intentions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from asf.agents._shared.code_agents import check_code_request
from asf.agents.base import Issue
from asf.agents.plan.milestones import (
    Milestone,
    MilestoneValidationError,
    parse_milestones,
)
from asf.contracts.models import AgentRequest, ApprovalFeedback, Artifact

NOW = datetime(2026, 11, 6, 0, 0, tzinfo=UTC)
FIX_AGENT = "agent-fix"
FIX_REQUIRED = {"SPEC", "PLAN", "TASK", "CODE"}
FIX_OPTIONAL = {"CODE_REVIEW", "TEST_REPORT"}


def make_artifact(kind: str, metadata: dict[str, Any] | None = None, **content: Any) -> Artifact:
    return Artifact(
        id=f"{kind.lower()}-1",
        type=kind,
        name=f"{kind}.json",
        version="1",
        content={"text": f"{kind} body text", **content},
        created_by="agent-x",
        created_at=NOW,
        metadata=metadata or {},
    )


def valid_artifacts() -> list[Artifact]:
    spec_link = {"specArtifactId": "spec-1", "specVersion": "1"}
    plan_link = {**spec_link, "planArtifactId": "plan-1", "planVersion": "1"}
    code_link = {
        **plan_link,
        "taskArtifactId": "task-1",
        "taskVersion": "1",
        "taskItemId": "T1",
        "baseRef": "main",
    }
    return [
        make_artifact("SPEC"),
        make_artifact("PLAN", spec_link),
        make_artifact("TASK", plan_link, tasks=[{"id": "T1", "description": "Do it"}]),
        make_artifact(
            "CODE",
            code_link,
            changeSet={
                "changes": [
                    {"path": "src/unit.py", "operation": "create", "content": "value = 1\n"}
                ]
            },
        ),
    ]


def make_request(**overrides: Any) -> AgentRequest:
    fields: dict[str, Any] = {
        "request_id": "r1",
        "task_id": "t1",
        "project_id": "p1",
        "workflow_id": "w1",
        "agent_id": FIX_AGENT,
        "input": {"taskItemId": "T1", "ref": "main"},
        "artifacts": valid_artifacts(),
    }
    fields.update(overrides)
    return AgentRequest(**fields)


def check_fix(request: AgentRequest) -> list[Issue]:
    """The Fix agent's calling profile of check_code_request."""
    return check_code_request(
        request,
        FIX_AGENT,
        FIX_REQUIRED,
        optional=FIX_OPTIONAL,
        require_ref=True,
        extra_input={"previousFixError"},
    )


def pairs(issues: list[Issue]) -> list[tuple[str, str]]:
    return [(issue.path, issue.message) for issue in issues]


def with_artifact(index: int, **updates: Any) -> list[Artifact]:
    artifacts = valid_artifacts()
    artifacts[index] = artifacts[index].model_copy(update=updates)
    return artifacts


def test_valid_fix_request_has_no_issues() -> None:
    assert check_fix(make_request()) == []


def test_valid_request_with_optional_artifacts_and_language() -> None:
    artifacts = valid_artifacts()
    artifacts.append(make_artifact("CODE_REVIEW", {}))
    request = make_request(
        input={"taskItemId": "T1", "ref": "main", "language": "en"},
        artifacts=artifacts,
    )
    assert check_fix(request) == []


def test_extra_input_field_is_allowed_when_declared() -> None:
    request = make_request(input={"taskItemId": "T1", "ref": "main", "previousFixError": "boom"})
    assert check_fix(request) == []


def test_attempt_two_in_metadata_is_allowed() -> None:
    assert check_fix(make_request(metadata={"attempt": 2})) == []


def test_wrong_agent_id_is_rejected() -> None:
    assert pairs(check_fix(make_request(agent_id="agent-other"))) == [
        ("agentId", "agentId does not match this agent")
    ]


@pytest.mark.parametrize("item_id", ["T0", "T01x", "X1", "t1", ""])
def test_malformed_task_item_ids_are_rejected(item_id: str) -> None:
    request = make_request(input={"taskItemId": item_id, "ref": "main"})
    assert ("input.taskItemId", "taskItemId must match T[1-9][0-9]*") in pairs(check_fix(request))


def test_missing_task_item_id_cascades_to_code_linkage() -> None:
    # The CODE artifact's metadata still names T1, so the missing input
    # id also fails the CODE task-item comparison — pinned as-is.
    assert pairs(check_fix(make_request(input={"ref": "main"}))) == [
        ("input.taskItemId", "taskItemId must match T[1-9][0-9]*"),
        ("artifacts[3].metadata.taskItemId", "CODE task item does not match"),
    ]


def test_unsupported_input_field_is_rejected() -> None:
    request = make_request(input={"taskItemId": "T1", "ref": "main", "bogus": 1})
    assert pairs(check_fix(request)) == [("input", "Unsupported input fields")]


@pytest.mark.parametrize("language", ["", "   ", 42])
def test_blank_or_nontext_language_is_rejected(language: Any) -> None:
    request = make_request(input={"taskItemId": "T1", "ref": "main", "language": language})
    assert pairs(check_fix(request)) == [("input.language", "language must be a non-empty string")]


def test_missing_ref_is_rejected_when_required() -> None:
    request = make_request(input={"taskItemId": "T1"})
    assert pairs(check_fix(request)) == [("input.ref", "A non-empty base ref is required")]


def test_feedback_on_the_request_is_rejected() -> None:
    feedback = [
        ApprovalFeedback(approval_id="a1", reviewer="rev", decision="REJECTED", comment="no")
    ]
    assert pairs(check_fix(make_request(feedback=feedback))) == [
        ("feedback", "Use review/report artifacts, not feedback")
    ]


@pytest.mark.parametrize("attempt", [0, -1, True, "2", 1.5])
def test_invalid_attempt_metadata_is_rejected(attempt: Any) -> None:
    assert pairs(check_fix(make_request(metadata={"attempt": attempt}))) == [
        ("metadata.attempt", "attempt must be an integer >= 1")
    ]


def test_missing_required_artifact_is_rejected() -> None:
    artifacts = [a for a in valid_artifacts() if a.type != "CODE"]
    assert pairs(check_fix(make_request(artifacts=artifacts))) == [
        ("artifacts", "Exactly one CODE artifact is required")
    ]


def test_duplicated_required_artifact_is_rejected() -> None:
    artifacts = valid_artifacts()
    artifacts.append(make_artifact("SPEC"))
    assert pairs(check_fix(make_request(artifacts=artifacts))) == [
        ("artifacts", "Exactly one SPEC artifact is required")
    ]


def test_unsupported_artifact_type_is_rejected() -> None:
    artifacts = valid_artifacts()
    artifacts.append(make_artifact("BOGUS"))
    assert pairs(check_fix(make_request(artifacts=artifacts))) == [
        ("artifacts[4]", "Unsupported artifact type")
    ]


@pytest.mark.parametrize("version", ["0", "01", "v1", ""])
def test_non_positive_integer_versions_are_rejected(version: str) -> None:
    artifacts = with_artifact(0, version=version)
    assert pairs(check_fix(make_request(artifacts=artifacts))) == [
        ("artifacts[0].version", "Artifact version must be a positive integer")
    ]


def test_blank_artifact_text_is_rejected() -> None:
    artifacts = with_artifact(1, content={"text": "   "})
    assert pairs(check_fix(make_request(artifacts=artifacts))) == [
        ("artifacts[1].content.text", "Non-empty inline text is required")
    ]


def test_non_dict_artifact_content_is_rejected() -> None:
    artifacts = with_artifact(0, content="plain string")
    assert pairs(check_fix(make_request(artifacts=artifacts))) == [
        ("artifacts[0].content.text", "Non-empty inline text is required")
    ]


def test_non_serializable_artifact_content_is_rejected() -> None:
    artifacts = with_artifact(0, content={"text": "x", "raw": object()})
    assert pairs(check_fix(make_request(artifacts=artifacts))) == [
        ("artifacts[0].content", "Artifact content must be JSON serializable")
    ]


def test_oversized_artifact_context_is_rejected() -> None:
    artifacts = with_artifact(0, content={"text": "x" * 1_100_000})
    assert pairs(check_fix(make_request(artifacts=artifacts))) == [
        ("artifacts", "Artifact context exceeds the size limit")
    ]


def test_code_without_base_ref_is_rejected() -> None:
    artifacts = valid_artifacts()
    metadata = {**artifacts[3].metadata, "baseRef": ""}
    artifacts[3] = artifacts[3].model_copy(update={"metadata": metadata})
    assert pairs(check_fix(make_request(artifacts=artifacts))) == [
        ("artifacts[3].metadata.baseRef", "CODE baseRef is required")
    ]


def test_code_for_a_different_task_item_is_rejected() -> None:
    artifacts = valid_artifacts()
    metadata = {**artifacts[3].metadata, "taskItemId": "T2"}
    artifacts[3] = artifacts[3].model_copy(update={"metadata": metadata})
    assert pairs(check_fix(make_request(artifacts=artifacts))) == [
        ("artifacts[3].metadata.taskItemId", "CODE task item does not match")
    ]


def test_invalid_code_changeset_is_rejected() -> None:
    artifacts = with_artifact(
        3,
        content={
            "text": "x",
            "changeSet": {"changes": [{"path": "a.py", "operation": "bogus"}]},
        },
    )
    assert pairs(check_fix(make_request(artifacts=artifacts))) == [
        ("artifacts[3].content.changeSet", "Invalid CODE ChangeSet")
    ]


def test_task_without_the_requested_item_is_rejected() -> None:
    artifacts = with_artifact(2, content={"text": "x", "tasks": [{"id": "T9"}]})
    assert pairs(check_fix(make_request(artifacts=artifacts))) == [
        ("artifacts.TASK", "TASK has no unique matching task item")
    ]


def test_task_with_the_item_twice_is_rejected() -> None:
    artifacts = with_artifact(2, content={"text": "x", "tasks": [{"id": "T1"}, {"id": "T1"}]})
    assert pairs(check_fix(make_request(artifacts=artifacts))) == [
        ("artifacts.TASK", "TASK has no unique matching task item")
    ]


def test_stale_upstream_traceability_is_rejected() -> None:
    artifacts = with_artifact(1, metadata={"specArtifactId": "spec-9", "specVersion": "1"})
    assert pairs(check_fix(make_request(artifacts=artifacts))) == [
        ("artifacts", "Stale upstream traceability")
    ]


def test_stale_code_traceability_is_rejected_per_link() -> None:
    artifacts = valid_artifacts()
    metadata = {**artifacts[3].metadata, "specVersion": "2"}
    artifacts[3] = artifacts[3].model_copy(update={"metadata": metadata})
    assert pairs(check_fix(make_request(artifacts=artifacts))) == [
        ("artifacts.CODE.metadata.specVersion", "Stale CODE traceability")
    ]


def test_traceability_checks_are_skipped_when_other_issues_exist() -> None:
    # The link checks run only on an otherwise-clean request: a stale
    # PLAN->SPEC link plus a blank language reports the language only.
    artifacts = with_artifact(1, metadata={"specArtifactId": "spec-9", "specVersion": "1"})
    request = make_request(
        input={"taskItemId": "T1", "ref": "main", "language": ""},
        artifacts=artifacts,
    )
    assert pairs(check_fix(request)) == [("input.language", "language must be a non-empty string")]


def test_test_agent_profile_accepts_task_and_code_only() -> None:
    artifacts = [a for a in valid_artifacts() if a.type in ("TASK", "CODE")]
    request = make_request(agent_id="agent-test", input={"taskItemId": "T1"}, artifacts=artifacts)
    assert check_code_request(request, "agent-test", {"TASK", "CODE"}) == []


def test_test_agent_profile_rejects_upstream_artifacts_as_unsupported() -> None:
    request = make_request(agent_id="agent-test", input={"taskItemId": "T1"})
    assert pairs(check_code_request(request, "agent-test", {"TASK", "CODE"})) == [
        ("artifacts[0]", "Unsupported artifact type"),
        ("artifacts[1]", "Unsupported artifact type"),
    ]


PLAN_TEXT = """# PLAN

### M1: Setup
- Deliverables: scaffolding
- Acceptance criteria: repo builds
- Depends on: none

### M2: Core
- Deliverables: engine
- Acceptance criteria: tests pass
- Depends on: M1
"""


def milestone_issues(text: str) -> list[str]:
    with pytest.raises(MilestoneValidationError) as caught:
        parse_milestones(text)
    return caught.value.issues


def test_well_formed_plan_parses_to_typed_milestones() -> None:
    assert parse_milestones(PLAN_TEXT) == [
        Milestone(
            id="M1",
            name="Setup",
            deliverables="scaffolding",
            acceptance_criteria="repo builds",
            depends_on=(),
        ),
        Milestone(
            id="M2",
            name="Core",
            deliverables="engine",
            acceptance_criteria="tests pass",
            depends_on=("M1",),
        ),
    ]


def test_multiple_dependencies_parse_in_order() -> None:
    text = (
        PLAN_TEXT
        + """
### M3: Polish
- Deliverables: docs
- Acceptance criteria: reviewed
- Depends on: M1, M2
"""
    )
    assert parse_milestones(text)[2].depends_on == ("M1", "M2")


def test_depends_on_none_is_case_insensitive() -> None:
    assert (
        parse_milestones(PLAN_TEXT.replace("Depends on: none", "Depends on: NONE"))[0].depends_on
        == ()
    )


def test_milestone_name_keeps_everything_after_the_first_colon() -> None:
    text = """### M1: Setup: phase one
- Deliverables: d
- Acceptance criteria: a
- Depends on: none
"""
    assert parse_milestones(text)[0].name == "Setup: phase one"


@pytest.mark.parametrize("text", ["", "# PLAN\nsome prose\n", "## M1: wrong heading level\n"])
def test_plan_without_milestone_headings_is_rejected(text: str) -> None:
    assert milestone_issues(text) == [
        "No milestones found (expected at least one '### M1: ...' heading)"
    ]


def test_missing_deliverables_field_is_rejected() -> None:
    assert milestone_issues(PLAN_TEXT.replace("- Deliverables: engine\n", "")) == [
        "Milestone M2: missing 'Deliverables' field"
    ]


def test_missing_acceptance_criteria_field_is_rejected() -> None:
    text = PLAN_TEXT.replace("- Acceptance criteria: repo builds\n", "")
    assert milestone_issues(text) == ["Milestone M1: missing 'Acceptance criteria' field"]


def test_missing_depends_on_field_is_rejected() -> None:
    assert milestone_issues(PLAN_TEXT.replace("- Depends on: none\n", "")) == [
        "Milestone M1: missing 'Depends on' field"
    ]


def test_empty_field_value_counts_as_missing() -> None:
    assert milestone_issues(PLAN_TEXT.replace("Deliverables: engine", "Deliverables:")) == [
        "Milestone M2: missing 'Deliverables' field"
    ]


def test_nonsequential_ids_are_rejected() -> None:
    text = PLAN_TEXT.replace("### M2: Core", "### M3: Core")
    assert milestone_issues(text) == ["Milestone IDs must be sequential: expected M2, got M3"]


def test_first_milestone_must_be_m1() -> None:
    text = PLAN_TEXT.replace("### M1: Setup", "### M2: Setup").replace(
        "### M2: Core", "### M3: Core"
    )
    # The renamed M3 still depends on the now-nonexistent M1, which
    # adds a third issue — pinned as the function reports it.
    assert milestone_issues(text) == [
        "Milestone IDs must be sequential: expected M1, got M2",
        "Milestone IDs must be sequential: expected M2, got M3",
        "Milestone M3: depends on later or non-existent milestone 'M1'",
    ]


def test_duplicate_ids_report_sequence_and_duplicate_issues() -> None:
    text = (
        PLAN_TEXT
        + """
### M1: Again
- Deliverables: x
- Acceptance criteria: y
- Depends on: none
"""
    )
    assert milestone_issues(text) == [
        "Milestone IDs must be sequential: expected M3, got M1",
        "Duplicate milestone ID: M1",
    ]


def test_forward_dependency_is_rejected() -> None:
    text = PLAN_TEXT.replace("Depends on: M1", "Depends on: M3")
    assert milestone_issues(text) == [
        "Milestone M2: depends on later or non-existent milestone 'M3'"
    ]


def test_unknown_dependency_is_rejected() -> None:
    text = PLAN_TEXT.replace("Depends on: M1", "Depends on: M9")
    assert milestone_issues(text) == [
        "Milestone M2: depends on later or non-existent milestone 'M9'"
    ]


def test_self_dependency_is_rejected() -> None:
    text = PLAN_TEXT.replace("Depends on: M1", "Depends on: M2")
    assert milestone_issues(text) == ["Milestone M2: self-dependency is not allowed"]


def test_more_than_twenty_milestones_is_rejected() -> None:
    text = "# PLAN\n" + "".join(
        f"### M{i}: N{i}\n- Deliverables: d\n- Acceptance criteria: a\n- Depends on: none\n\n"
        for i in range(1, 22)
    )
    assert milestone_issues(text) == ["Too many milestones: 21 (maximum 20)"]


def test_error_message_joins_the_issues_with_newlines() -> None:
    with pytest.raises(MilestoneValidationError) as caught:
        parse_milestones("")
    assert str(caught.value) == (
        "No milestones found (expected at least one '### M1: ...' heading)"
    )
