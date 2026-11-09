from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from itertools import count
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from asf.agents._shared import security
from asf.agents.base import AgentRuntime
from asf.agents.test import TestAgent as RunnerAgent
from asf.agents.test import build_test_agent
from asf.agents.test.agent import MAX_ARG_CHARS, MAX_ARGS
from asf.configuration.platform import PlatformConfig
from asf.contracts.models import AgentRequest, Artifact, ModelRequest, ModelResponse
from asf.tools.changeset import ChangeSet
from asf.tools.ports import (
    AppliedRelabel,
    CommandResult,
    CommandSpec,
    CommandTimeoutError,
    SandboxError,
    SandboxResult,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


class NoModels:
    def complete(self, request: ModelRequest) -> ModelResponse:
        raise AssertionError("TestAgent must never call a model")


class FakeSandbox:
    def __init__(self, result: SandboxResult | None = None, error: Exception | None = None) -> None:
        self.result = (
            result if result is not None else SandboxResult((CommandResult(0, "ok", "", 10),))
        )
        self.error = error
        self.calls: list[tuple[tuple[CommandSpec, ...], ChangeSet, str]] = []

    def run(
        self,
        commands: Sequence[CommandSpec],
        changes: ChangeSet,
        ref: str,
        *,
        fail_fast: bool = True,
    ) -> SandboxResult:
        self.calls.append((tuple(commands), changes, ref))
        self.fail_fast_seen = fail_fast
        if self.error is not None:
            raise self.error
        return self.result


def runtime() -> AgentRuntime:
    ids = count(1)
    return AgentRuntime(NoModels(), lambda: NOW, lambda: f"id-{next(ids)}")


def artifact(kind: str, content: dict[str, Any], metadata: dict[str, Any]) -> Artifact:
    return Artifact(
        id=kind.lower() + "-1",
        type=kind,
        name=kind,
        version="1",
        content=content,
        created_by="upstream",
        created_at=NOW,
        metadata=metadata,
    )


def request(commands: Any = None) -> AgentRequest:
    task = artifact(
        "TASK",
        {
            "text": "Tasks",
            "tasks": [
                {
                    "id": "T1",
                    "expectedFiles": ["test_app.py"],
                    "verificationHint": "never-execute-this",
                }
            ],
        },
        {
            "specArtifactId": "spec-1",
            "specVersion": "1",
            "planArtifactId": "plan-1",
            "planVersion": "1",
        },
    )
    code = artifact(
        "CODE",
        {
            "text": "Code",
            "changeSet": {
                "changes": [{"path": "test_app.py", "operation": "create", "content": "pass\n"}]
            },
        },
        {
            "specArtifactId": "spec-1",
            "specVersion": "1",
            "planArtifactId": "plan-1",
            "planVersion": "1",
            "taskArtifactId": task.id,
            "taskVersion": task.version,
            "taskItemId": "T1",
            "baseRef": "commit-1",
        },
    )
    return AgentRequest(
        request_id="request-1",
        task_id="task-1",
        project_id="project-1",
        workflow_id="workflow-1",
        agent_id="agent-test",
        input={"taskItemId": "T1"},
        context={"project": {"testCommands": [["pytest", "-q"]] if commands is None else commands}},
        artifacts=[task, code],
    )


def test_runs_all_commands_once_at_code_ref_and_emits_report_schema() -> None:
    sandbox = FakeSandbox(
        SandboxResult(
            (
                CommandResult(0, "first", "", 1),
                CommandResult(0, "second", "", 2),
            )
        )
    )
    req = request([["pytest", "-q"], [r".\tools\verify", "a; b", "|"]])
    req.input["ref"] = "ignored-ref"
    result = RunnerAgent(runtime(), sandbox).execute(req)
    assert result.status == "SUCCESS"
    assert len(sandbox.calls) == 1
    commands, changes, ref = sandbox.calls[0]
    assert ref == "commit-1"
    assert commands == (
        CommandSpec(("pytest", "-q")),
        CommandSpec((r".\tools\verify", "a; b", "|")),
    )
    assert isinstance(req.artifacts[1].content, dict)
    assert changes == ChangeSet.model_validate(req.artifacts[1].content["changeSet"])
    report = result.artifacts[0]
    assert report.type == "TEST_REPORT"
    assert report.metadata == {
        **req.artifacts[1].metadata,
        "codeArtifactId": "code-1",
        "codeVersion": "1",
    }
    assert isinstance(report.content, dict)
    assert set(report.content) == {"format", "report", "text"}
    assert report.content["format"] == "json"
    assert result.output == report.content["report"]
    assert report.content["report"]["verdict"] == "PASS"
    assert report.content["report"]["summary"] == "PASS: 2/2 commands passed"
    assert report.content["text"].strip()
    assert report.content["report"]["commands"][0] == {
        "argv": ["pytest", "-q"],
        "exitCode": 0,
        "stdout": "first",
        "stderr": "",
        "durationMs": 1,
    }
    root = Path(__file__).resolve().parents[2]
    schema = json.loads((root / "contracts" / "schemas" / "contracts.schema.json").read_text())
    validator = Draft202012Validator({"$ref": "#/$defs/Artifact", "$defs": schema["$defs"]})
    assert not list(validator.iter_errors(report.to_contract()))
    content_schema = {
        "type": "object",
        "required": ["commands", "verdict", "summary", "relabels"],
        "additionalProperties": False,
        "properties": {
            "verdict": {"enum": ["PASS", "FAIL"]},
            "summary": {"type": "string", "minLength": 1},
            "relabels": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["path", "fromOperation", "toOperation"],
                    "properties": {
                        "path": {"type": "string"},
                        "fromOperation": {"type": "string"},
                        "toOperation": {"type": "string"},
                    },
                },
            },
            "commands": {
                "type": "array",
                "minItems": 1,
                "maxItems": 20,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["argv", "exitCode", "stdout", "stderr", "durationMs"],
                    "properties": {
                        "argv": {"type": "array", "items": {"type": "string"}},
                        "exitCode": {"type": "integer"},
                        "stdout": {"type": "string"},
                        "stderr": {"type": "string"},
                        "durationMs": {"type": "integer", "minimum": 0},
                    },
                },
            },
        },
    }
    wrapper_schema = {
        "type": "object",
        "required": ["format", "report", "text"],
        "additionalProperties": False,
        "properties": {
            "format": {"const": "json"},
            "report": content_schema,
            "text": {"type": "string", "minLength": 1},
        },
    }
    assert not list(Draft202012Validator(wrapper_schema).iter_errors(report.content))


def test_report_records_sandbox_relabels() -> None:
    sandbox = FakeSandbox(
        SandboxResult(
            (CommandResult(0, "ok", "", 1),),
            relabels=(AppliedRelabel("docs/testing/decisions.md", "modify", "create"),),
        )
    )
    result = RunnerAgent(runtime(), sandbox).execute(request())
    assert result.status == "SUCCESS"
    report = result.artifacts[0]
    assert isinstance(report.content, dict)
    assert report.content["report"]["relabels"] == [
        {
            "path": "docs/testing/decisions.md",
            "fromOperation": "modify",
            "toOperation": "create",
        }
    ]


@pytest.mark.parametrize("exit_code", [1, 2, 5, -1])
def test_test_failure_is_successful_agent_execution(exit_code: int) -> None:
    sandbox = FakeSandbox(SandboxResult((CommandResult(exit_code, "", "failed", 1),)))
    result = RunnerAgent(runtime(), sandbox).execute(request())
    assert result.status == "SUCCESS"
    assert isinstance(result.output, dict)
    assert result.output["verdict"] == "FAIL"
    assert result.errors == []


@pytest.mark.parametrize(
    "commands",
    [
        [],
        "pytest",
        [[""]],
        [["  "]],
        [[]],
        [("pytest",)],
        [[1]],
        [["pytest", ""]],
        [["pytest", "\x00"]],
        [["pytest", "\ud800"]],
        [["pytest", "a" * (MAX_ARG_CHARS + 1)]],
        [["pytest"] * (MAX_ARGS + 1)],
        [["pytest"]] * 21,
        [["../pytest"]],
        [[r"..\pytest"]],
        [[r"bin\..\pytest"]],
        [[r"bin/..\pytest"]],
        [["/bin/pytest"]],
        [[r"\bin\pytest"]],
        [[r"C:\tools\pytest"]],
        [["C:pytest"]],
        [[r"\\host\share\pytest"]],
        [["//host/share/pytest"]],
        [["pytest:stream"]],
    ],
)
def test_invalid_commands_rejected_without_sandbox(commands: Any) -> None:
    sandbox = FakeSandbox()
    result = RunnerAgent(runtime(), sandbox).execute(request(commands))
    assert result.status == "REJECTED"
    assert all(error.code == "VALIDATION_FAILED" for error in result.errors)
    assert not sandbox.calls


@pytest.mark.parametrize("executable", ["pytest", "./pytest", r".\pytest", "tools/pytest"])
def test_relative_commands_allowed_without_shell_heuristics(executable: str) -> None:
    sandbox = FakeSandbox()
    result = RunnerAgent(runtime(), sandbox).execute(request([[executable, "&&", "$data"]]))
    assert result.status == "SUCCESS"
    assert sandbox.calls[0][0][0].argv == (executable, "&&", "$data")


@pytest.mark.parametrize(
    "context", [{}, {"project": None}, {"project": []}, {"project": {"testCommands": None}}]
)
def test_missing_project_commands_rejected(context: dict[str, Any]) -> None:
    req = request().model_copy(update={"context": context})
    sandbox = FakeSandbox()
    assert RunnerAgent(runtime(), sandbox).execute(req).status == "REJECTED"
    assert not sandbox.calls


@pytest.mark.parametrize(
    "mutation",
    [
        "taskItemId",
        "missingTask",
        "duplicateCode",
        "invalidCode",
        "staleTask",
        "wrongTaskItem",
        "missingRef",
        "missingTaskItem",
        "duplicateTaskItem",
    ],
)
def test_task_code_validation_and_traceability(mutation: str) -> None:
    req = request()
    assert isinstance(req.artifacts[0].content, dict)
    assert isinstance(req.artifacts[1].content, dict)
    if mutation == "taskItemId":
        req.input["taskItemId"] = "T0"
    elif mutation == "missingTask":
        req.artifacts.pop(0)
    elif mutation == "duplicateCode":
        req.artifacts.append(req.artifacts[1])
    elif mutation == "invalidCode":
        req.artifacts[1].content["changeSet"] = {}
    elif mutation == "staleTask":
        req.artifacts[1].metadata["taskVersion"] = "2"
    elif mutation == "wrongTaskItem":
        req.artifacts[1].metadata["taskItemId"] = "T2"
    elif mutation == "missingRef":
        req.artifacts[1].metadata.pop("baseRef")
    elif mutation == "missingTaskItem":
        req.artifacts[0].content["tasks"] = []
    else:
        req.artifacts[0].content["tasks"] *= 2
    sandbox = FakeSandbox()
    assert RunnerAgent(runtime(), sandbox).execute(req).status == "REJECTED"
    assert not sandbox.calls


@pytest.mark.parametrize("mode", ["sandbox", "unexpected", "timeout", "commandTimeout"])
def test_runner_errors_are_safe(mode: str) -> None:
    private = fake_secret()
    errors = {
        "sandbox": SandboxError(private),
        "unexpected": RuntimeError(private),
        "timeout": TimeoutError(private),
        "commandTimeout": CommandTimeoutError(CommandSpec(("pytest", private))),
    }
    sandbox = FakeSandbox(error=errors[mode])
    result = RunnerAgent(runtime(), sandbox).execute(request())
    expected = "COMMAND_TIMEOUT" if mode in {"timeout", "commandTimeout"} else "SANDBOX_ERROR"
    assert result.status == "FAILED"
    assert result.errors[0].code == expected
    assert result.errors[0].category == "INTEGRATION"
    assert result.errors[0].retryable
    assert not result.artifacts
    assert bool(private not in result.model_dump_json()), "Exception text leaked"


@pytest.mark.parametrize("duration,timed_out", [(120001, False), (1, True)])
def test_result_timeout_is_infrastructure_failure(duration: int, timed_out: bool) -> None:
    sandbox = FakeSandbox(SandboxResult((CommandResult(0, "", "", duration, timed_out),)))
    result = RunnerAgent(runtime(), sandbox).execute(request())
    assert result.status == "FAILED"
    assert result.errors[0].code == "COMMAND_TIMEOUT"
    assert result.artifacts == []


def test_timeout_exact_boundary_is_allowed() -> None:
    sandbox = FakeSandbox(SandboxResult((CommandResult(0, "", "", 120000),)))
    assert RunnerAgent(runtime(), sandbox).execute(request()).status == "SUCCESS"


@pytest.mark.parametrize(
    "items",
    [
        (),
        (CommandResult(0, "", "", 1), CommandResult(0, "", "", 1)),
        (None,),
        (CommandResult(0, "", "", -1),),
        (CommandResult(0, "", "", True),),
        (CommandResult(True, "", "", 1),),
    ],
)
def test_malformed_sandbox_results_are_infrastructure_failures(items: Any) -> None:
    sandbox = FakeSandbox(SandboxResult(items))
    result = RunnerAgent(runtime(), sandbox).execute(request())
    assert result.status == "FAILED"
    assert result.errors[0].code == "SANDBOX_ERROR"
    assert result.artifacts == []


def fake_secret() -> str:
    return "glpat" + "-" + "t" * 91


def test_full_secret_matches_redacted_before_utf8_truncation() -> None:
    private = fake_secret()
    limit = CommandSpec(("pytest",)).output_limit_bytes
    prefix = "é" * ((limit - 3) // 2)
    sandbox = FakeSandbox(
        SandboxResult(
            (CommandResult(0, prefix + private + "tail", private + "\n" + "界" * limit, 1),)
        )
    )
    result = RunnerAgent(runtime(), sandbox).execute(request([["pytest", private]]))
    assert result.status == "SUCCESS"
    assert isinstance(result.output, dict)
    command = result.output["commands"][0]
    assert bool(private not in result.model_dump_json()), "Secret leaked"
    assert bool("t" * 20 not in result.model_dump_json()), "Secret suffix leaked"
    assert command["argv"][1] == "[REDACTED]"
    assert command["stderr"].startswith("[REDACTED]")
    for stream in ("stdout", "stderr"):
        assert len(command[stream].encode("utf-8")) <= limit
        assert "\ufffd" not in command[stream]


def test_shared_runtime_patterns_and_overlapping_full_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = "sensitive" + "-" + "a" * 100
    monkeypatch.setattr(
        security,
        "SECRET_PATTERNS",
        [
            ("short", re.compile(re.escape(private[:30]))),
            ("full", re.compile(re.escape(private))),
        ],
    )
    req = request()
    req.artifacts[1].metadata["baseRef"] = private
    sandbox = FakeSandbox(SandboxResult((CommandResult(0, private, private, 1),)))
    result = RunnerAgent(runtime(), sandbox).execute(req)
    assert result.status == "SUCCESS"
    assert isinstance(result.output, dict)
    assert bool(private not in result.model_dump_json()), "Secret leaked"
    assert result.output["commands"][0]["stdout"] == "[REDACTED]"
    assert result.artifacts[0].metadata["baseRef"] == "[REDACTED]"
    assert bool(sandbox.calls[0][2] == private), "Sandbox ref changed"


def test_nontext_traceability_rejected_and_unrelated_metadata_not_propagated() -> None:
    req = request()
    req.artifacts[1].metadata["specArtifactId"] = {"untrusted": fake_secret()}
    sandbox = FakeSandbox()
    result = RunnerAgent(runtime(), sandbox).execute(req)
    assert result.status == "REJECTED"
    assert not sandbox.calls
    assert bool(fake_secret() not in result.model_dump_json()), "Metadata leaked"
    req.artifacts[1].metadata["specArtifactId"] = "spec-1"
    req.artifacts[1].metadata["untrusted"] = fake_secret()
    result = RunnerAgent(runtime(), sandbox).execute(req)
    assert result.status == "SUCCESS"
    assert "untrusted" not in result.artifacts[0].metadata


def test_factory_never_reads_templates_or_uses_models() -> None:
    sandbox = FakeSandbox()
    agent = build_test_agent(runtime(), PlatformConfig(), Path("nonexistent-templates"), sandbox)
    assert agent.get_metadata().id == "agent-test"
    assert agent.validate(request()).valid
    assert agent.execute(request()).status == "SUCCESS"


def test_twenty_commands_are_allowed() -> None:
    sandbox = FakeSandbox(SandboxResult((CommandResult(0, "", "", 1),) * 20))
    result = RunnerAgent(runtime(), sandbox).execute(request([["pytest"]] * 20))
    assert result.status == "SUCCESS"
    assert len(sandbox.calls) == 1
    assert len(sandbox.calls[0][0]) == 20
