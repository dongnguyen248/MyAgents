from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from asf.agents.base import AgentRuntime
from asf.agents.fix import FixAgent, FixSettings, build_fix_agent
from asf.agents.fix.prompts import FixPrompts
from asf.configuration.platform import PlatformConfig
from asf.contracts.models import AgentRequest, Artifact
from asf.models.errors import ModelGatewayError
from asf.models.fake import ScriptedModelGateway
from asf.tools.fake import InMemoryRepository
from asf.tools.ports import FileTooLargeError, RepositoryError
from tests.unit._fake_secrets import fake_secret
from tests.unit.contract_models import validator_for
from tests.unit.implement_helpers import (
    T_AWARE,
    counter_id,
    make_agent_and_gateway,
    make_implement_request,
    make_valid_changeset_reply,
)


def fix_request() -> AgentRequest:
    request = make_implement_request()
    implement, _ = make_agent_and_gateway([make_valid_changeset_reply()])
    result = implement.execute(request)
    if result.status != "SUCCESS":
        raise AssertionError("Implement fixture failed")
    code = result.artifacts[0]
    review = Artifact(
        id="review-1",
        type="CODE_REVIEW",
        name="CODE_REVIEW.md",
        version="1",
        content={
            "format": "json",
            "text": "Changes requested",
            "review": {"findings": [], "verdict": "CHANGES_REQUESTED"},
        },
        created_by="agent-review",
        created_at=T_AWARE,
        metadata={"codeArtifactId": code.id, "codeVersion": code.version, "taskItemId": "T1"},
    )
    return request.model_copy(
        update={"agent_id": "agent-fix", "artifacts": [*request.artifacts, code, review]}
    )


def fix_agent(
    replies: list[Any], repository: InMemoryRepository | None = None
) -> tuple[FixAgent, ScriptedModelGateway]:
    gateway = ScriptedModelGateway(replies)
    return FixAgent(
        AgentRuntime(gateway, lambda: T_AWARE, counter_id("fix-")),
        repository or InMemoryRepository(),
        FixSettings(
            prompts=FixPrompts("Return a complete replacement ChangeSet"),
            # This suite was written against the legacy JSON contract:
            # pin it (and no repair loop) explicitly.
            edit_format="json",
            repair_attempts=0,
        ),
    ), gateway


def test_fix_creates_replacement_with_traceability_and_contract():
    agent, gateway = fix_agent([make_valid_changeset_reply()])
    request = fix_request()
    result = agent.execute(request)
    assert result.status == "SUCCESS"
    code = result.artifacts[0]
    original = next(a for a in request.artifacts if a.type == "CODE")
    assert code.version == "2"
    assert code.metadata["revisionOf"] == original.id
    assert code.metadata["fixedReviewIds"] == ["review-1"]
    assert code.metadata["fixedTestReportIds"] == []
    assert code.metadata["baseRef"] == "main"
    assert code.content["changeSet"]["changes"][0]["operation"] == "create"
    assert result.metrics.revision_count == 1
    assert len(gateway.requests) == 1
    validator_for("Artifact").validate(code.to_contract())
    validator_for("AgentResult").validate(result.to_contract())


@pytest.mark.parametrize(
    "change",
    [
        "wrong-agent",
        "missing-code",
        "missing-task",
        "missing-report",
        "stale-id",
        "stale-version",
        "wrong-task",
        "wrong-ref",
        "attempt",
        "unknown",
        "bad-code",
        "bad-task",
        "bad-version",
        "duplicate-report",
    ],
)
def test_fix_rejects_invalid_input_without_model_call(change: str):
    request = fix_request()
    artifacts = list(request.artifacts)
    if change == "wrong-agent":
        request = request.model_copy(update={"agent_id": "wrong"})
    elif change.startswith("missing-"):
        kind = {"missing-code": "CODE", "missing-task": "TASK", "missing-report": "CODE_REVIEW"}[
            change
        ]
        artifacts = [a for a in artifacts if a.type != kind]
    elif change in {"stale-id", "stale-version", "wrong-task"}:
        report = artifacts[-1]
        key = {
            "stale-id": "codeArtifactId",
            "stale-version": "codeVersion",
            "wrong-task": "taskItemId",
        }[change]
        artifacts[-1] = report.model_copy(update={"metadata": {**report.metadata, key: "wrong"}})
    elif change == "wrong-ref":
        request = request.model_copy(update={"input": {**request.input, "ref": "other"}})
    elif change == "attempt":
        request = request.model_copy(update={"metadata": {"attempt": True}})
    elif change == "unknown":
        artifacts.append(artifacts[0].model_copy(update={"type": "UNKNOWN"}))
    elif change == "bad-code":
        artifacts[-2] = artifacts[-2].model_copy(update={"content": {"text": "bad"}})
    elif change == "bad-task":
        artifacts[2] = artifacts[2].model_copy(update={"content": {"text": "{}"}})
    elif change == "bad-version":
        artifacts[0] = artifacts[0].model_copy(update={"version": "0"})
    elif change == "duplicate-report":
        artifacts.append(artifacts[-1])
    request = request.model_copy(update={"artifacts": artifacts})
    agent, gateway = fix_agent([])
    result = agent.execute(request)
    assert result.status == "REJECTED"
    assert not result.artifacts
    assert not gateway.requests


@pytest.mark.parametrize(
    "reply",
    ["", "not-json", "[]", '{"changes":[]}', '{"changes":[{}]}'],
)
def test_fix_rejects_invalid_model_reply(reply: str):
    agent, _ = fix_agent([reply])
    result = agent.execute(fix_request())
    assert result.status == "FAILED"
    assert result.errors[0].code == "LLM_INVALID_RESPONSE"
    # Unified policy: invalid model replies are retryable (see
    # agents/_shared/model_errors); the retry policy decides.
    assert result.errors[0].retryable is True
    assert not result.artifacts


def test_fix_invalid_reply_error_keeps_the_parse_cause():
    # "Invalid replacement ChangeSet" alone is undiagnosable: the
    # recorded error must keep WHY the reply was rejected (plus the
    # reply's size and finish reason), because the next fix attempt is
    # told this error verbatim and a human reads it on the run page.
    agent, _ = fix_agent(["not-json"])
    result = agent.execute(fix_request())
    assert result.status == "FAILED"
    error = result.errors[0]
    assert error.message == "Invalid replacement ChangeSet"
    assert error.details["cause"]
    assert error.details["replyChars"] == len("not-json")
    assert error.details["finishReason"] == "stop"


def test_fix_previous_attempt_error_reaches_the_prompt():
    # A re-attempt (step retry / resumed run) carries the previous
    # rejection in its input; it must reach the model's payload so the
    # model can correct that specific failure instead of repeating it.
    agent, gateway = fix_agent([make_valid_changeset_reply()])
    base = fix_request()
    request = base.model_copy(
        update={
            "input": {
                **base.input,
                "previousFixError": (
                    "LLM_INVALID_RESPONSE: Invalid replacement ChangeSet"
                    ' — {"cause": "Invalid JSON"}'
                ),
            },
        }
    )
    result = agent.execute(request)
    assert result.status == "SUCCESS"
    payload = json.loads(gateway.requests[0].messages[1].content)
    assert "Invalid replacement ChangeSet" in payload["previousAttemptError"]

    agent, gateway = fix_agent([make_valid_changeset_reply()])
    result = agent.execute(fix_request())
    assert result.status == "SUCCESS"
    payload = json.loads(gateway.requests[0].messages[1].content)
    assert "previousAttemptError" not in payload


@pytest.mark.parametrize(
    ("path", "operation"),
    [("src/other.py", "create"), (".env", "create"), ("src/calculator.py", "delete")],
)
def test_fix_enforces_scope_and_base_existence(path: str, operation: str):
    change: dict[str, Any] = {"path": path, "operation": operation}
    if operation != "delete":
        change["content"] = "value = 1"
    agent, _ = fix_agent([json.dumps({"changes": [change]})])
    result = agent.execute(fix_request())
    assert result.status == "FAILED"
    assert result.errors[0].code == "LLM_INVALID_RESPONSE"


def test_fix_create_for_existing_file_is_treated_as_modify():
    """The replacement is relative to the original base ref, where the
    file did not exist — but a local workspace already holds the
    implemented file, so the model's "create" is normalized to the
    "modify" it means instead of failing the run (Dong's live case)."""
    repository = InMemoryRepository({"main": {"src/calculator.py": "value = 0"}})
    agent, _ = fix_agent([make_valid_changeset_reply()], repository)
    result = agent.execute(fix_request())
    assert result.status == "SUCCESS"
    code = result.artifacts[0]
    assert code.content["changeSet"]["changes"][0]["operation"] == "modify"


def test_fix_modify_for_missing_file_is_treated_as_create():
    change = {"path": "src/calculator.py", "operation": "modify", "content": "value = 1"}
    agent, _ = fix_agent([json.dumps({"changes": [change]})])
    result = agent.execute(fix_request())
    assert result.status == "SUCCESS"
    code = result.artifacts[0]
    assert code.content["changeSet"]["changes"][0]["operation"] == "create"


def test_fix_secret_rejection_never_echoes_value():
    secret = fake_secret("aws_access")
    reply = make_valid_changeset_reply(
        changes=[{"path": "src/calculator.py", "operation": "create", "content": secret}]
    )
    agent, _ = fix_agent([reply])
    result = agent.execute(fix_request())
    assert result.status == "FAILED"
    assert "secretIssues" in result.errors[0].details
    assert secret not in json.dumps(result.to_contract())


@pytest.mark.parametrize("error_code", ["LLM_TIMEOUT", "LLM_RATE_LIMITED"])
def test_fix_preserves_gateway_errors(error_code: str):
    agent, _ = fix_agent([ModelGatewayError(error_code, "Model unavailable")])
    result = agent.execute(fix_request())
    assert result.status == "FAILED"
    assert result.errors[0].code == error_code


def test_fix_repository_error_is_explicit_and_does_not_call_model():
    class BrokenRepository(InMemoryRepository):
        def read_file(self, path: str, ref: str, max_bytes: int = 256_000) -> str:
            raise RepositoryError("Unavailable")

    agent, gateway = fix_agent([], BrokenRepository())
    result = agent.execute(fix_request())
    assert result.status == "FAILED"
    assert result.errors[0].code == "REPOSITORY_ERROR"
    assert not gateway.requests


def test_fix_oversized_base_does_not_call_model():
    class OversizedRepository(InMemoryRepository):
        def read_file(self, path: str, ref: str, max_bytes: int = 256_000) -> str:
            raise FileTooLargeError(path, ref, max_bytes)

    agent, gateway = fix_agent([], OversizedRepository())
    result = agent.execute(fix_request())
    assert result.errors[0].code == "VALIDATION_FAILED"
    assert result.status == "REJECTED"
    assert not result.events
    assert not gateway.requests


def test_fix_complete_replacement_remains_relative_to_original_base():
    repo = InMemoryRepository({"main": {"src/calculator.py": "value = 1"}})
    request = fix_request()
    code = next(a for a in request.artifacts if a.type == "CODE")
    updated = code.model_copy(
        update={
            "content": {
                "text": "Previous complete code",
                "changeSet": {
                    "changes": [
                        {"path": "src/calculator.py", "operation": "modify", "content": "value = 2"}
                    ]
                },
            }
        }
    )
    request = request.model_copy(
        update={"artifacts": [updated if a.type == "CODE" else a for a in request.artifacts]}
    )
    reply = make_valid_changeset_reply(
        changes=[{"path": "src/calculator.py", "operation": "modify", "content": "value = 3"}]
    )
    agent, _ = fix_agent([reply], repo)
    result = agent.execute(request)
    assert result.status == "SUCCESS"
    assert repo.read_file("src/calculator.py", "main") == "value = 1"
    assert result.artifacts[0].metadata["baseRef"] == "main"


def test_fix_factory_loads_packaged_prompts():
    root = Path(__file__).resolve().parents[2]
    platform = PlatformConfig()
    runtime = AgentRuntime(ScriptedModelGateway([]), lambda: T_AWARE, counter_id())
    agent = build_fix_agent(runtime, platform, root / "templates", InMemoryRepository())
    assert agent.metadata.id == "agent-fix"


@pytest.mark.parametrize(
    "project",
    ["invalid-json", "[]", {"enabledSkills": "not-a-list"}, {"enabledSkills": [" "]}],
)
def test_fix_rejects_invalid_project_context_before_model(project: Any):
    request = fix_request().model_copy(update={"context": {"project": project}})
    agent, gateway = fix_agent([])
    result = agent.execute(request)
    assert result.status == "REJECTED"
    assert not gateway.requests


@pytest.mark.parametrize("files", [None, [], "module.py", [42], ["../outside.py"], ["a", "a"]])
def test_fix_rejects_malformed_expected_files(files: Any):
    request = fix_request()
    task = next(a for a in request.artifacts if a.type == "TASK")
    task_data = json.loads(task.content["text"])
    task_data["tasks"][0]["expectedFiles"] = files
    replacement = task.model_copy(update={"content": {"text": json.dumps(task_data)}})
    request = request.model_copy(
        update={
            "artifacts": [replacement if a.type == "TASK" else a for a in request.artifacts],
        }
    )
    agent, gateway = fix_agent([])
    result = agent.execute(request)
    assert result.status == "REJECTED"
    assert not gateway.requests


def test_fix_uses_one_enabled_skills_line_and_no_skill_contents():
    request = fix_request().model_copy(
        update={
            "context": {"project": json.dumps({"enabledSkills": ["python", "testing"]})},
        }
    )
    agent, gateway = fix_agent([make_valid_changeset_reply()])
    result = agent.execute(request)
    assert result.status == "SUCCESS"
    system = gateway.requests[0].messages[0].content
    assert system.count("Enabled skills:") == 1
    assert "Enabled skills: python, testing" in system


def test_fix_enforces_raw_reply_size(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("asf.agents.fix.agent.MAX_REPLY_CHARS", 20)
    agent, _ = fix_agent([make_valid_changeset_reply()])
    result = agent.execute(fix_request())
    assert result.status == "FAILED"
    assert result.errors[0].code == "LLM_INVALID_RESPONSE"


def test_fix_enforces_rendered_size(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("asf.agents.fix.agent.MAX_TEXT_CHARS", 1)
    agent, _ = fix_agent([make_valid_changeset_reply()])
    result = agent.execute(fix_request())
    assert result.status == "FAILED"
    assert result.errors[0].code == "LLM_INVALID_RESPONSE"


def test_fix_handles_repository_failure_during_generated_validation():
    class LaterFailure(InMemoryRepository):
        def __init__(self) -> None:
            super().__init__()
            self.reads = 0

        def read_file(self, path: str, ref: str, max_bytes: int = 256_000) -> str:
            self.reads += 1
            if self.reads > 1:
                raise RepositoryError("Unavailable")
            return super().read_file(path, ref, max_bytes)

    agent, gateway = fix_agent([make_valid_changeset_reply()], LaterFailure())
    result = agent.execute(fix_request())
    assert result.status == "FAILED"
    assert result.errors[0].code == "REPOSITORY_ERROR"
    assert len(gateway.requests) == 1


@pytest.mark.parametrize("text", ["[]", '{"tasks":null}', '{"tasks":[]}'])
def test_fix_rejects_task_without_unique_item(text: str):
    request = fix_request()
    request = request.model_copy(
        update={
            "artifacts": [
                a.model_copy(update={"content": {"text": text}}) if a.type == "TASK" else a
                for a in request.artifacts
            ],
        }
    )
    agent, gateway = fix_agent([])
    result = agent.execute(request)
    assert result.status == "REJECTED"
    assert not gateway.requests


@pytest.mark.parametrize("language", [None, "", 42])
def test_fix_rejects_invalid_language(language: Any):
    request = fix_request()
    request = request.model_copy(update={"input": {**request.input, "language": language}})
    agent, gateway = fix_agent([])
    result = agent.execute(request)
    assert result.status == "REJECTED"
    assert not gateway.requests


_TWO_FILE_CHANGES = [
    {
        "path": "src/calculator.py",
        "operation": "create",
        "content": "def add(a, b):\n    return a + b\n",
    },
    {
        "path": "src/extra.py",
        "operation": "create",
        "content": "def extra():\n    return 1\n",
    },
]

_EDITED_CALCULATOR = "def add(a, b):\n    return a + b  # sum of the two operands\n"


def two_file_fix_request() -> AgentRequest:
    request = make_implement_request(expected_files=["src/calculator.py", "src/extra.py"])
    implement, _ = make_agent_and_gateway([make_valid_changeset_reply(changes=_TWO_FILE_CHANGES)])
    result = implement.execute(request)
    if result.status != "SUCCESS":
        raise AssertionError("Implement fixture failed")
    code = result.artifacts[0]
    review = Artifact(
        id="review-1",
        type="CODE_REVIEW",
        name="CODE_REVIEW.md",
        version="1",
        content={
            "format": "json",
            "text": "Changes requested",
            "review": {"findings": [], "verdict": "CHANGES_REQUESTED"},
        },
        created_by="agent-review",
        created_at=T_AWARE,
        metadata={"codeArtifactId": code.id, "codeVersion": code.version, "taskItemId": "T1"},
    )
    return request.model_copy(
        update={"agent_id": "agent-fix", "artifacts": [*request.artifacts, code, review]}
    )


def fix_agent_blocks(
    replies: list[Any],
) -> tuple[FixAgent, ScriptedModelGateway]:
    gateway = ScriptedModelGateway(replies)
    return FixAgent(
        AgentRuntime(gateway, lambda: T_AWARE, counter_id("fix-")),
        InMemoryRepository(),
        FixSettings(
            prompts=FixPrompts("Return a complete replacement ChangeSet"),
            edit_format="blocks",
            repair_attempts=0,
        ),
    ), gateway


def test_fix_blocks_mode_replacement_is_cumulative():
    reply = (
        "FILE: src/calculator.py\n"
        "<<<<<<< SEARCH\n"
        "    return a + b\n"
        "=======\n"
        "    return a + b  # sum of the two operands\n"
        ">>>>>>> REPLACE\n"
    )
    agent, _ = fix_agent_blocks([reply])
    result = agent.execute(two_file_fix_request())
    assert result.status == "SUCCESS"
    changes = result.artifacts[0].content["changeSet"]["changes"]
    by_path = {change["path"]: change for change in changes}
    assert set(by_path) == {"src/calculator.py", "src/extra.py"}
    assert by_path["src/calculator.py"]["content"] == _EDITED_CALCULATOR
    assert by_path["src/extra.py"]["operation"] == "create"
    assert by_path["src/extra.py"]["content"] == "def extra():\n    return 1\n"


def test_fix_json_mode_replacement_drops_untouched_previous_files():
    # Characterization of current behaviour (FIX-3 item 2): the JSON
    # path returns the model's ChangeSet as the whole replacement —
    # there is no compose step — so a reply naming one file silently
    # drops every other file the previous changeset created.
    reply = make_valid_changeset_reply(
        changes=[
            {
                "path": "src/calculator.py",
                "operation": "create",
                "content": _EDITED_CALCULATOR,
            }
        ]
    )
    agent, _ = fix_agent([reply])
    result = agent.execute(two_file_fix_request())
    assert result.status == "SUCCESS"
    changes = result.artifacts[0].content["changeSet"]["changes"]
    assert [change["path"] for change in changes] == ["src/calculator.py"]
