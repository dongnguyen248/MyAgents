"""Phase 12: the artifact-review agent end to end (scripted gateway)."""

from __future__ import annotations

import itertools
import json
from datetime import UTC, datetime
from typing import Any

from asf.agents.artifact_review.agent import ArtifactReviewAgent, ArtifactReviewSettings
from asf.agents.base import AgentRuntime
from asf.agents.loading import load_artifact_review_prompts
from asf.contracts.models import AgentRequest, AgentResult, Artifact, PlatformError
from asf.models.fake import ScriptedModelGateway
from tests.unit.test_artifact_review_checks import GOOD_SPEC, spec_artifact

NOW = datetime(2026, 1, 1, tzinfo=UTC)
APPROVE_REPLY = '{"findings": [], "summary": "The artifact is complete and consistent."}'
BLOCKER_REPLY = json.dumps(
    {
        "findings": [
            {
                "id": "F-001",
                "severity": "BLOCKER",
                "category": "COMPLETENESS",
                "location": "## Scope (in / out)",
                "problem": "Out-of-scope work is not stated.",
                "required_change": "State what is out of scope.",
                "status": "NEW",
            }
        ],
        "summary": "One blocking gap.",
    }
)


def make_agent(replies: list[str]) -> tuple[ArtifactReviewAgent, ScriptedModelGateway]:
    gateway = ScriptedModelGateway(replies)
    ids = itertools.count(1)
    runtime = AgentRuntime(
        models=gateway,
        clock=lambda: NOW,
        new_id=lambda: f"review-{next(ids)}",
    )
    settings = ArtifactReviewSettings(prompts=load_artifact_review_prompts())
    return ArtifactReviewAgent(runtime, settings), gateway


def make_request(
    *,
    stage: str = "spec",
    round_number: int = 1,
    artifacts: list[Artifact] | None = None,
    previous: dict[str, Any] | None = None,
) -> AgentRequest:
    arts = artifacts if artifacts is not None else [spec_artifact()]
    if previous is not None:
        arts = [
            *arts,
            Artifact(
                id="artifact-review-1",
                type="ARTIFACT_REVIEW",
                name="ARTIFACT_REVIEW.json",
                version="1",
                content={"format": "json", "review": previous, "text": "previous review"},
                created_by="agent-artifact-review",
                created_at=NOW,
                metadata={},
            ),
        ]
    return AgentRequest(
        request_id="request-1",
        task_id="task-1",
        project_id="project-1",
        workflow_id="software-development",
        agent_id="agent-artifact-review",
        input={"stage": stage, "round": round_number},
        context={"project": {"name": "Demo", "technology": {"backend": ["python"]}}},
        artifacts=arts,
    )


def review_of(result: AgentResult) -> dict[str, Any]:
    artifact = result.artifacts[0]
    assert artifact.type == "ARTIFACT_REVIEW"
    return artifact.content["review"]  # type: ignore[index]


def test_agent_approves_a_clean_spec() -> None:
    agent, gateway = make_agent([APPROVE_REPLY])
    result = agent.execute(make_request())
    assert result.status == "SUCCESS"
    assert result.output == {"verdict": "APPROVE", "stage": "spec", "round": 1, "findings": 0}
    artifact = result.artifacts[0]
    assert artifact.metadata["reviewedArtifactId"] == "spec-1"
    assert artifact.metadata["verdict"] == "APPROVE"
    assert artifact.metadata["findingCounts"] == {
        "BLOCKER": 0,
        "MAJOR": 0,
        "MINOR": 0,
        "NIT": 0,
    }
    assert len(gateway.requests) == 1
    system = gateway.requests[0].messages[0].content
    assert "independent artifact reviewer" in system
    assert "Stage checklist: SPEC" in system


def test_agent_requests_changes_on_a_blocker_finding() -> None:
    agent, _gateway = make_agent([BLOCKER_REPLY])
    result = agent.execute(make_request())
    assert result.output["verdict"] == "REQUEST_CHANGES"
    review = review_of(result)
    assert review["findings"][0]["id"] == "F-001"
    assert result.artifacts[0].metadata["findingIds"] == ["F-001"]


def test_mechanical_blocker_short_circuits_the_model() -> None:
    agent, gateway = make_agent([APPROVE_REPLY])
    broken = spec_artifact(GOOD_SPEC.replace("## Open questions\nNone.\n", ""))
    result = agent.execute(make_request(artifacts=[broken]))
    assert result.output["verdict"] == "REQUEST_CHANGES"
    assert gateway.requests == []
    review = review_of(result)
    assert review["findings"][0]["source"] == "mechanical"
    assert "skipped for this round" in review["summary"]


def test_agent_carries_forward_unmentioned_previous_findings() -> None:
    previous = {
        "findings": [
            {
                "id": "F-001",
                "severity": "MAJOR",
                "category": "CLARITY",
                "location": "## Scope (in / out)",
                "problem": "Ambiguous scope line.",
                "required_change": "Pick one meaning.",
                "status": "NEW",
            }
        ],
        "summary": "Round 1.",
    }
    agent, _gateway = make_agent([APPROVE_REPLY])
    result = agent.execute(make_request(round_number=2, previous=previous))
    assert result.output["verdict"] == "REQUEST_CHANGES"
    review = review_of(result)
    assert [finding["id"] for finding in review["findings"]] == ["F-001"]
    assert review["findings"][0]["status"] == "STILL_OPEN"


def test_agent_rejects_a_reply_with_a_verdict_field() -> None:
    agent, _gateway = make_agent(['{"findings": [], "summary": "ok", "verdict": "APPROVE"}'])
    result = agent.execute(make_request())
    assert result.status == "FAILED"
    assert result.errors[0].code == "LLM_INVALID_RESPONSE"


def _rejection(reply: str) -> PlatformError:
    agent, _gateway = make_agent([reply])
    result = agent.execute(make_request())
    assert result.status == "FAILED"
    assert result.errors[0].code == "LLM_INVALID_RESPONSE"
    return result.errors[0]


def _finding(**overrides: Any) -> dict[str, Any]:
    finding: dict[str, Any] = {
        "id": "F-001",
        "severity": "BLOCKER",
        "category": "TRACEABILITY",
        "location": "REQ-2",
        "problem": "REQ-2 has no acceptance criterion.",
        "required_change": "Add an acceptance criterion for REQ-2.",
    }
    finding.update(overrides)
    return finding


def test_rejection_reason_for_a_non_json_reply() -> None:
    error = _rejection("not json at all")
    assert error.details["reason"] == "not valid JSON"
    assert "not valid JSON" in error.message


def test_rejection_reason_for_prose_before_the_json() -> None:
    error = _rejection('Here is my review: {"findings": [], "summary": "ok"}')
    assert error.details["reason"] == "extra text before the JSON"
    assert "Here is my review" not in error.message


def test_rejection_reason_for_prose_after_the_json() -> None:
    error = _rejection('{"findings": [], "summary": "ok"} hope this helps')
    assert error.details["reason"] == "extra text after the JSON value"
    assert "hope this helps" not in error.message


def test_rejection_reason_for_missing_fields() -> None:
    error = _rejection("{}")
    assert "missing field 'findings'" in error.details["reason"]
    assert "missing field 'summary'" in error.details["reason"]


def test_rejection_reason_for_an_unexpected_field() -> None:
    error = _rejection('{"findings": [], "summary": "ok", "verdict": "APPROVE"}')
    assert error.details["reason"] == "unexpected field 'verdict'"


def test_rejection_reason_for_an_unknown_enum_value() -> None:
    reply = json.dumps({"findings": [_finding(severity="CRITICAL")], "summary": "ok"})
    error = _rejection(reply)
    reason = error.details["reason"]
    assert reason.startswith("unknown value at 'findings.0.severity' (expected ")
    assert "'BLOCKER'" in reason
    assert "CRITICAL" not in error.message


def test_rejection_reason_for_a_wrong_type() -> None:
    error = _rejection('{"findings": {}, "summary": "ok"}')
    assert error.details["reason"] == "wrong type at 'findings'"


def test_rejection_reason_for_a_missing_finding_field() -> None:
    finding = _finding()
    del finding["problem"]
    error = _rejection(json.dumps({"findings": [finding], "summary": "ok"}))
    assert error.details["reason"] == "missing field 'findings.0.problem'"


def test_rejection_reason_for_too_many_findings() -> None:
    reply = json.dumps({"findings": [_finding()] * 21, "summary": "ok"})
    error = _rejection(reply)
    assert error.details["reason"] == "'findings' has too many items (max 20)"


def test_rejection_reason_for_a_waived_blocker() -> None:
    reply = json.dumps(
        {"findings": [_finding(status="WAIVED", waiver_reason="accepted")], "summary": "ok"}
    )
    error = _rejection(reply)
    assert error.details["reason"] == "findings.0: A BLOCKER finding can never be WAIVED"


def test_rejection_reason_for_a_blank_summary() -> None:
    error = _rejection('{"findings": [], "summary": "  "}')
    assert error.details["reason"] == "summary: String fields must not be blank"


def test_rejection_reason_is_capped_at_240_chars() -> None:
    reply = json.dumps(
        {"findings": [_finding(category="STYLE"), _finding(category="TASTE")], "summary": "ok"}
    )
    error = _rejection(reply)
    reason = error.details["reason"]
    assert len(reason) <= 240
    assert reason.startswith("unknown value at 'findings.0.category'")


def test_rejection_reason_redacts_secret_shaped_field_names() -> None:
    error = _rejection(
        '{"findings": [], "summary": "ok", "bearer abcdefghijklmnopqrstuvwxyz123456": 1}'
    )
    assert "abcdefghijklmnopqrstuvwxyz123456" not in error.message
    assert "[REDACTED]" in error.details["reason"]


def test_agent_accepts_a_fenced_reply_unchanged() -> None:
    agent, _gateway = make_agent(["```json\n" + APPROVE_REPLY + "\n```"])
    result = agent.execute(make_request())
    assert result.status == "SUCCESS"
    assert result.output["verdict"] == "APPROVE"


def test_agent_request_validation() -> None:
    agent, gateway = make_agent([APPROVE_REPLY])
    bad_stage = make_request(stage="code")
    assert agent.execute(bad_stage).status == "REJECTED"
    missing = make_request(artifacts=[])
    assert agent.execute(missing).status == "REJECTED"
    assert gateway.requests == []


def test_metadata_carries_the_model_profile_when_configured() -> None:
    gateway = ScriptedModelGateway([])
    ids = itertools.count(1)
    runtime = AgentRuntime(
        models=gateway,
        clock=lambda: NOW,
        new_id=lambda: f"review-{next(ids)}",
    )
    settings = ArtifactReviewSettings(
        prompts=load_artifact_review_prompts(), model_profile="strong"
    )
    agent = ArtifactReviewAgent(runtime, settings)
    assert agent.get_metadata().configuration == {"modelProfile": "strong"}
