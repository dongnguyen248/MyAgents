from __future__ import annotations

import copy
import importlib.resources
import itertools
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

import asf.agents.loading as loading
import asf.agents.review.agent as review_module
from asf.agents.base import AgentRuntime
from asf.agents.review import ReviewAgent, ReviewPrompts, ReviewSettings, build_review_agent
from asf.agents.review.prompts import (
    MAX_FINDINGS,
    ReviewContent,
    build_review_messages,
    render_review_markdown,
)
from asf.configuration.platform import PlatformConfig
from asf.contracts.models import AgentRequest, AgentResult, Artifact
from asf.models.errors import ModelGatewayError
from asf.models.fake import ScriptedModelGateway
from tests.unit.contract_models import validator_for

NOW = datetime(2026, 11, 2, tzinfo=UTC)
APPROVE = '{"findings": [], "verdict": "APPROVE"}'


def make_request() -> AgentRequest:
    def artifact(kind: str, metadata: dict[str, Any], **content: Any) -> Artifact:
        return Artifact(
            id=f"{kind.lower()}-1",
            type=kind,
            name=f"{kind}.json",
            version="1",
            content={"format": "json", "text": f"{kind} inline context", **content},
            created_by=f"agent-{kind.lower()}",
            created_at=NOW,
            metadata=metadata,
        )

    spec_link = {"specArtifactId": "spec-1", "specVersion": "1"}
    plan_link = {**spec_link, "planArtifactId": "plan-1", "planVersion": "1"}
    code_link = {
        **plan_link,
        "taskArtifactId": "task-1",
        "taskVersion": "1",
        "taskItemId": "T1",
        "baseRef": "base-ref",
    }
    return AgentRequest(
        request_id="request-review",
        task_id="workflow-task",
        project_id="project-review",
        workflow_id="workflow-review",
        agent_id="agent-review",
        input={"taskItemId": "T1"},
        artifacts=[
            artifact("SPEC", {}),
            artifact("PLAN", spec_link),
            artifact(
                "TASK",
                plan_link,
                tasks=[
                    {
                        "id": "T1",
                        "description": "Implement the unit",
                        "expectedFiles": ["src/unit.py", "old.py"],
                    }
                ],
            ),
            artifact(
                "CODE",
                code_link,
                changeSet={
                    "changes": [
                        {"path": "src/unit.py", "operation": "create", "content": "value = 1\n"},
                        {"path": "old.py", "operation": "delete"},
                    ]
                },
            ),
        ],
    )


def make_agent(
    reply: str | Exception = APPROVE,
    *,
    prompts: ReviewPrompts | None = None,
) -> tuple[ReviewAgent, ScriptedModelGateway]:
    gateway = ScriptedModelGateway([reply])
    ids = itertools.count(1)
    runtime = AgentRuntime(
        models=gateway, clock=lambda: NOW, new_id=lambda: f"generated-{next(ids)}"
    )
    return ReviewAgent(
        runtime,
        ReviewSettings(
            prompts=prompts or ReviewPrompts(system="Review submitted code."),
            model="review-model",
            parameters={"temperature": 0.1},
        ),
    ), gateway


def finding(**overrides: Any) -> dict[str, Any]:
    return {
        "severity": "ERROR",
        "path": "src/unit.py",
        "line": 1,
        "description": "The value must satisfy the requirement.",
        "suggestion": "Use two.",
        **overrides,
    }


def reply_for(findings: list[dict[str, Any]], verdict: str = "CHANGES_REQUESTED") -> str:
    return json.dumps({"findings": findings, "verdict": verdict})


def assert_success(result: AgentResult) -> Artifact:
    assert result.status == "SUCCESS"
    assert not result.errors
    assert len(result.artifacts) == 1
    validator_for("AgentResult").validate(result.to_contract())
    validator_for("Artifact").validate(result.artifacts[0].to_contract())
    return result.artifacts[0]


def assert_invalid(result: AgentResult) -> None:
    assert result.status == "FAILED"
    assert result.output is None
    assert result.artifacts == []
    assert len(result.errors) == 1
    error = result.errors[0]
    # Unified policy (agents/_shared/model_errors): an unusable model
    # reply is retryable; whether a step retries is the retry policy's
    # decision, not the agent's.
    assert (error.code, error.category, error.retryable) == (
        "LLM_INVALID_RESPONSE",
        "LLM",
        True,
    )
    assert error.details == {}
    assert result.events[-1].event_type == "AGENT_FAILED"


@pytest.mark.parametrize("verdict", ["APPROVE", "CHANGES_REQUESTED"])
def test_success_has_schema_valid_artifact_and_injected_traceability(verdict: str) -> None:
    request = make_request()
    before = request.to_contract()
    agent, gateway = make_agent(reply_for([], verdict))
    result = agent.execute(request)
    artifact = assert_success(result)
    assert isinstance(artifact.content, dict)
    assert artifact.type == "CODE_REVIEW"
    assert artifact.version == "1"
    assert artifact.created_by == "agent-review"
    assert artifact.created_at == NOW
    assert artifact.content["review"] == {"findings": [], "verdict": verdict}
    assert artifact.content["format"] == "json"
    assert artifact.content["text"].startswith("# CODE_REVIEW")
    assert result.output == {"verdict": verdict}
    assert artifact.metadata == {
        **request.artifacts[-1].metadata,
        "codeArtifactId": "code-1",
        "codeVersion": "1",
    }
    assert request.to_contract() == before
    assert len(gateway.requests) == 1
    call = gateway.requests[0]
    validator_for("ModelRequest").validate(call.to_contract())
    assert call.model == "review-model"
    assert call.parameters == {"temperature": 0.1}
    assert call.metadata["requestId"] == request.request_id
    assert result.metrics.revision_count == 0
    assert [event.event_type for event in result.events] == [
        "AGENT_STARTED",
        "ARTIFACT_CREATED",
        "AGENT_COMPLETED",
    ]


@pytest.mark.parametrize("severity", ["ERROR", "WARNING", "INFO"])
@pytest.mark.parametrize("path", ["src/unit.py", "old.py"])
def test_findings_render_and_preserve_fields(severity: str, path: str) -> None:
    item = finding(severity=severity, path=path)
    agent, _ = make_agent(reply_for([item]))
    artifact = assert_success(agent.execute(make_request()))
    assert isinstance(artifact.content, dict)
    assert artifact.content["review"]["findings"] == [item]
    assert f"## Finding: {path}:1 [{severity}]" in artifact.content["text"]
    assert "Suggestion: Use two." in artifact.content["text"]


@pytest.mark.parametrize("severity", ["WARNING", "INFO"])
def test_approve_allows_nonblocking_findings_with_optional_fields(severity: str) -> None:
    item = {"severity": severity, "path": "src/unit.py", "description": "Consider simplifying."}
    agent, _ = make_agent(reply_for([item], "APPROVE"))
    artifact = assert_success(agent.execute(make_request()))
    assert isinstance(artifact.content, dict)
    assert artifact.content["review"]["findings"] == [item]
    assert "Suggestion:" not in artifact.content["text"]


@pytest.mark.parametrize(
    "payload",
    [
        "",
        " \n\t",
        "not-json",
        "[]",
        "null",
        "42",
        '{"findings": [], "verdict": "APPROVE"',
        '{"findings": [], "verdict": "UNKNOWN"}',
        '{"findings": [], "verdict": " "}',
        '{"findings": [], "verdict": "APPROVE", "metadata": {}}',
        '{"verdict": "APPROVE"}',
        '{"findings": null, "verdict": "APPROVE"}',
        '{"findings": {}, "verdict": "APPROVE"}',
        reply_for([finding()], "APPROVE"),
        reply_for([finding(path="outside.py")]),
        reply_for([finding(path="./src/unit.py")]),
        reply_for([finding(path=" \t")]),
        reply_for([finding(path=None)]),
        reply_for([finding(description=" \n")]),
        reply_for([finding(description=7)]),
        reply_for([finding(description=None)]),
        reply_for([finding(suggestion="\n\t")]),
        reply_for([finding(suggestion=7)]),
        reply_for([finding(severity="CRITICAL")]),
        reply_for([finding(severity=" ")]),
        reply_for([finding(line=0)]),
        reply_for([finding(line=-1)]),
        reply_for([finding(line=True)]),
        reply_for([finding(line=1.5)]),
        reply_for([finding(line="1")]),
        reply_for([finding(unexpected="ignored?")]),
        reply_for([finding()] * (MAX_FINDINGS + 1)),
    ],
)
def test_invalid_reply_fails_nonretryably_without_artifacts(payload: str) -> None:
    agent, gateway = make_agent(payload)
    assert_invalid(agent.execute(make_request()))
    assert len(gateway.requests) == 1


def test_validation_error_never_echoes_model_payload() -> None:
    marker = "untrusted-private-diagnostic-marker"
    agent, _ = make_agent(reply_for([finding(line=marker)]))
    result = agent.execute(make_request())
    assert_invalid(result)
    assert marker not in json.dumps(result.to_contract())
    assert "ValidationError" not in json.dumps(result.to_contract())


def test_parse_error_never_echoes_model_payload() -> None:
    marker = "untrusted-parser-diagnostic-marker"
    agent, _ = make_agent('{"findings": [' + marker)
    result = agent.execute(make_request())
    assert_invalid(result)
    assert marker not in json.dumps(result.to_contract())


@pytest.mark.parametrize("field", ["severity", "path", "description"])
def test_required_finding_fields_cannot_be_omitted(field: str) -> None:
    item = finding()
    item.pop(field)
    agent, _ = make_agent(reply_for([item]))
    assert_invalid(agent.execute(make_request()))


def test_optional_finding_fields_allow_null() -> None:
    agent, _ = make_agent(reply_for([finding(line=None, suggestion=None)]))
    artifact = assert_success(agent.execute(make_request()))
    assert isinstance(artifact.content, dict)
    stored = artifact.content["review"]["findings"][0]
    assert "line" not in stored
    assert "suggestion" not in stored


def test_accepts_fenced_json_and_maximum_findings() -> None:
    payload = reply_for([finding()] * MAX_FINDINGS)
    agent, _ = make_agent(f"```json\n{payload}\n```")
    artifact = assert_success(agent.execute(make_request()))
    assert isinstance(artifact.content, dict)
    assert len(artifact.content["review"]["findings"]) == MAX_FINDINGS


@pytest.mark.parametrize("extra", [0, 1])
def test_raw_reply_size_boundary(extra: int) -> None:
    payload = APPROVE + " " * (review_module.MAX_REPLY_CHARS - len(APPROVE) + extra)
    agent, gateway = make_agent(payload)
    result = agent.execute(make_request())
    if extra:
        assert_invalid(result)
    else:
        assert_success(result)
    assert len(gateway.requests) == 1


@pytest.mark.parametrize("extra", [0, 1])
def test_rendered_size_boundary(monkeypatch: pytest.MonkeyPatch, extra: int) -> None:
    review = ReviewContent.model_validate_json(APPROVE)
    size = len(render_review_markdown(review, "code-1", "1"))
    monkeypatch.setattr(review_module, "MAX_TEXT_CHARS", size - extra)
    agent, _ = make_agent()
    result = agent.execute(make_request())
    if extra:
        assert_invalid(result)
    else:
        assert_success(result)


@pytest.mark.parametrize(
    "problem",
    [
        "agent",
        "missing-task-item",
        "bad-task-item",
        "unknown-input",
        "feedback",
        "attempt",
        "missing-spec",
        "duplicate-code",
        "unknown-artifact",
        "version",
        "blank-text",
        "task-missing",
        "task-duplicate",
        "task-malformed",
        "bad-changes",
        "empty-changes",
        "code-task-link",
        "base-ref",
        "code-spec-link",
        "task-plan-link",
        "plan-spec-link",
    ],
)
def test_bad_request_rejected_without_model_call(problem: str) -> None:
    data = make_request().to_contract()
    if problem == "agent":
        data["agentId"] = "agent-other"
    elif problem == "missing-task-item":
        data["input"] = {}
    elif problem == "bad-task-item":
        data["input"]["taskItemId"] = "T0"
    elif problem == "unknown-input":
        data["input"]["feedback"] = "revise"
    elif problem == "feedback":
        data["feedback"] = [
            {
                "approvalId": "approval-1",
                "decision": "REJECTED",
                "reviewer": "reviewer",
                "comment": "No.",
            }
        ]
    elif problem == "attempt":
        data["metadata"]["attempt"] = True
    elif problem == "missing-spec":
        data["artifacts"].pop(0)
    elif problem == "duplicate-code":
        data["artifacts"].append(copy.deepcopy(data["artifacts"][-1]))
    elif problem == "unknown-artifact":
        data["artifacts"][0]["type"] = "UNKNOWN"
    elif problem == "version":
        data["artifacts"][0]["version"] = "0"
    elif problem == "blank-text":
        data["artifacts"][0]["content"]["text"] = " \n"
    elif problem == "task-missing":
        data["artifacts"][2]["content"]["tasks"] = [{"id": "T2"}]
    elif problem == "task-duplicate":
        data["artifacts"][2]["content"]["tasks"] *= 2
    elif problem == "task-malformed":
        data["artifacts"][2]["content"] = {"text": "not-json"}
    elif problem == "bad-changes":
        data["artifacts"][3]["content"]["changeSet"]["changes"][0]["content"] = None
    elif problem == "empty-changes":
        data["artifacts"][3]["content"]["changeSet"]["changes"] = []
    elif problem == "code-task-link":
        data["artifacts"][3]["metadata"]["taskItemId"] = "T2"
    elif problem == "base-ref":
        data["artifacts"][3]["metadata"].pop("baseRef")
    elif problem == "code-spec-link":
        data["artifacts"][3]["metadata"]["specVersion"] = "2"
    elif problem == "task-plan-link":
        data["artifacts"][2]["metadata"]["planVersion"] = "2"
    elif problem == "plan-spec-link":
        data["artifacts"][1]["metadata"]["specVersion"] = "2"
    request = AgentRequest.model_validate(data)
    agent, gateway = make_agent()
    validation = agent.validate(request)
    assert not validation.valid
    result = agent.execute(request)
    assert result.status == "REJECTED"
    assert all(error.code == "VALIDATION_FAILED" for error in result.errors)
    assert all(not error.retryable and error.category == "VALIDATION" for error in result.errors)
    assert result.artifacts == []
    assert result.events == []
    assert gateway.requests == []


def test_context_size_rejected_before_model() -> None:
    request = make_request()
    assert isinstance(request.artifacts[0].content, dict)
    request.artifacts[0].content["text"] = "x" * 1_000_001
    agent, gateway = make_agent()
    assert agent.execute(request).status == "REJECTED"
    assert not gateway.requests


@pytest.mark.parametrize(
    "code",
    [
        "LLM_TIMEOUT",
        "LLM_RATE_LIMITED",
        "INTEGRATION_UNAVAILABLE",
        "LLM_INVALID_RESPONSE",
    ],
)
def test_model_port_errors_preserve_failure_contract(code: str) -> None:
    agent, gateway = make_agent(ModelGatewayError(code, "Safe model port failure"))
    result = agent.execute(make_request())
    if code == "LLM_INVALID_RESPONSE":
        assert_invalid(result)
    else:
        assert result.status == "FAILED"
        assert result.errors[0].code == code
        assert result.errors[0].retryable
    assert len(gateway.requests) == 1
    assert result.artifacts == []


def test_unexpected_port_exception_does_not_expose_exception_text() -> None:
    marker = "private-exception-marker"
    agent, _ = make_agent(RuntimeError(marker))
    result = agent.execute(make_request())
    assert result.status == "FAILED"
    assert result.errors[0].code == "AGENT_EXECUTION_FAILED"
    assert marker not in json.dumps(result.to_contract())


def test_provider_invalid_response_message_is_preserved() -> None:
    # A provider-side failure (HTTP 400) arrives at the agent as a
    # gateway LLM_INVALID_RESPONSE; replacing it with a generic
    # "invalid review response" sentence hid the actual cause.
    agent, _ = make_agent(
        ModelGatewayError(
            "LLM_INVALID_RESPONSE",
            "Model provider error (HTTP 400): The requested model is not supported.",
        )
    )
    result = agent.execute(make_request())
    assert result.status == "FAILED"
    assert result.errors[0].code == "LLM_INVALID_RESPONSE"
    assert "Model provider error (HTTP 400)" in result.errors[0].message


def test_schema_rejection_logs_field_problems_without_values(
    caplog: pytest.LogCaptureFixture,
) -> None:
    marker = "untrusted-private-diagnostic-marker"
    agent, _ = make_agent(reply_for([finding(line=marker)]))
    with caplog.at_level(logging.WARNING, logger="asf.agents.review.agent"):
        result = agent.execute(make_request())
    assert_invalid(result)  # the result contract stays echo-free
    assert "findings.0.line" in caplog.text
    assert marker not in caplog.text


@pytest.mark.parametrize(
    "project",
    [
        {"enabledSkills": ["python", "quality"]},
        json.dumps({"enabledSkills": ["python", "quality"]}),
    ],
)
def test_skills_have_one_system_line_without_content_blocks(project: Any) -> None:
    request = make_request()
    request.context["project"] = project
    prompts = ReviewPrompts(system="Review.\nEnabled skills: obsolete\n")
    agent, gateway = make_agent(prompts=prompts)
    assert_success(agent.execute(request))
    system = gateway.requests[0].messages[0].content
    assert system == "Review.\nEnabled skills: python, quality"
    assert system.count("Enabled skills:") == 1


@pytest.mark.parametrize(
    "project",
    [
        None,
        [],
        "not-json",
        "[]",
        {"enabledSkills": "python"},
        {"enabledSkills": [None, 42, " "]},
    ],
)
def test_invalid_skill_context_is_safe(project: Any) -> None:
    request = make_request()
    request.context["project"] = project
    messages = build_review_messages(prompts=ReviewPrompts("Review."), request=request)
    assert messages[0].content == "Review.\nEnabled skills: none"


def test_prompt_contains_structured_code_and_only_selected_project_fields() -> None:
    request = make_request()
    request.context["project"] = {
        "name": "sample",
        "enabledSkills": ["python\nquality"],
        "skillContent": "Do not import this skill instruction block",
    }
    messages = build_review_messages(prompts=ReviewPrompts("Review."), request=request)
    assert messages[0].content == "Review.\nEnabled skills: python quality"
    data = json.loads(messages[1].content.split("\n", 1)[1])
    assert data["project"] == {"name": "sample"}
    assert data["taskItem"]["id"] == "T1"
    assert data["changeSet"]["changes"][0]["content"] == "value = 1\n"
    assert data["changeSet"]["changes"][1]["operation"] == "delete"
    assert "skillContent" not in messages[1].content


def test_task_item_json_text_and_nondefault_versions_are_supported() -> None:
    request = make_request()
    task = request.artifacts[2]
    assert isinstance(task.content, dict)
    task.content["text"] = json.dumps({"tasks": task.content.pop("tasks")})
    data = request.to_contract()
    data["artifacts"][3]["version"] = "3"
    data["metadata"]["attempt"] = 2
    request = AgentRequest.model_validate(data)
    agent, _ = make_agent()
    result = agent.execute(request)
    artifact = assert_success(result)
    assert artifact.metadata["codeVersion"] == "3"
    assert result.metrics.attempt == 2
    assert artifact.version == "1"


@pytest.mark.parametrize("configured", [False, True])
def test_factory_uses_loader_and_review_profile(
    monkeypatch: pytest.MonkeyPatch, configured: bool
) -> None:
    prompts = ReviewPrompts("Packaged review prompt")
    monkeypatch.setattr(loading, "load_review_prompts", lambda: prompts, raising=False)
    platform_data: dict[str, Any] = {}
    if configured:
        platform_data = {
            "models": {
                "profiles": {
                    "review": {
                        "provider": "fake",
                        "model": "configured-review",
                        "parameters": {"temperature": 0},
                    }
                }
            },
            "agents": {"review": {"modelProfile": "review"}},
        }
    gateway = ScriptedModelGateway([APPROVE])
    ids = itertools.count()
    runtime = AgentRuntime(models=gateway, clock=lambda: NOW, new_id=lambda: f"id-{next(ids)}")
    agent = build_review_agent(runtime, PlatformConfig.model_validate(platform_data), Path("."))
    assert_success(agent.execute(make_request()))
    call = gateway.requests[0]
    assert call.model == ("configured-review" if configured else None)
    assert call.parameters == ({"temperature": 0} if configured else {})
    assert call.messages[0].content.startswith(prompts.system)


def test_packaged_system_prompt_is_available() -> None:
    resource = importlib.resources.files("asf.agents.review").joinpath("prompts", "system.md")
    prompt = resource.read_text(encoding="utf-8")
    assert "APPROVE" in prompt
    assert "CHANGES_REQUESTED" in prompt
    agent, _ = make_agent(prompts=ReviewPrompts(prompt))
    assert_success(agent.execute(make_request()))


def test_real_loader_and_factory_integration_uses_packaged_prompt() -> None:
    gateway = ScriptedModelGateway([APPROVE])
    ids = itertools.count()
    runtime = AgentRuntime(models=gateway, clock=lambda: NOW, new_id=lambda: f"id-{next(ids)}")
    agent = build_review_agent(runtime, PlatformConfig(), Path("."))
    assert_success(agent.execute(make_request()))
    assert gateway.requests[0].messages[0].content.startswith(loading.load_review_prompts().system)


def test_project_review_rules_become_system_criteria() -> None:
    request = make_request()
    request.context["project"] = {
        "reviewRules": "Never hardcode an HTTP status code.",
    }
    messages = build_review_messages(prompts=ReviewPrompts("Review."), request=request)
    system = messages[0].content
    assert system.startswith("Review.\nEnabled skills: none")
    assert "Project review rules" in system
    assert "Never hardcode an HTTP status code." in system
    # Rules are configuration, not data: they never enter the payload.
    assert "reviewRules" not in messages[1].content
    assert "Never hardcode" not in messages[1].content


@pytest.mark.parametrize("rules", [None, "", "   ", 42, ["rule"], {"text": "rule"}])
def test_absent_or_invalid_review_rules_leave_prompt_unchanged(rules: Any) -> None:
    request = make_request()
    request.context["project"] = {"reviewRules": rules}
    messages = build_review_messages(prompts=ReviewPrompts("Review."), request=request)
    assert messages[0].content == "Review.\nEnabled skills: none"
