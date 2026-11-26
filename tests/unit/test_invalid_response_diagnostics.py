from __future__ import annotations

import json

import pytest

from asf.agents._shared.response_diagnostics import (
    EXCERPT_MAX_CHARS,
    ResponseEvidence,
    diagnostic_details,
    error_offset,
)
from asf.agents.base import AgentExecutionError
from asf.agents.task.parse import parse_tasks
from asf.contracts.models import ModelResponse, ModelUsage


def _response(content: str) -> ModelResponse:
    return ModelResponse(
        content=content,
        model="test-model",
        usage=ModelUsage(prompt_tokens=1, completion_tokens=1),
        finish_reason="stop",
    )


def test_error_offset_from_json_decode_error() -> None:
    text = '{"a": 1 "b": 2}'
    with pytest.raises(json.JSONDecodeError) as caught:
        json.loads(text)
    assert error_offset(caught.value, text) == text.index('"b"')


def test_diagnostic_details_without_offset_has_no_excerpt() -> None:
    details = diagnostic_details(ResponseEvidence("not json", "stop"))
    assert details == {"replyChars": 8, "finishReason": "stop", "repairsAttempted": 0}


def test_excerpt_is_bounded_and_covers_offset() -> None:
    text = "word " * 80 + "NEEDLE" + " word" * 80
    offset = text.index("NEEDLE")
    details = diagnostic_details(ResponseEvidence(text, "stop", offset=offset))
    assert len(details["excerpt"]) <= EXCERPT_MAX_CHARS
    assert "NEEDLE" in details["excerpt"]


def test_excerpt_redacts_runtime_built_secret() -> None:
    secret = "".join(chr(97 + (i % 26)) for i in range(32))
    text = "x" * 120 + f' api_key = "{secret}" ' + "y" * 120
    offset = text.index(secret)
    details = diagnostic_details(ResponseEvidence(text, "stop", offset=offset))
    assert secret not in details["excerpt"]
    assert "[REDACTED]" in details["excerpt"]


def test_task_parse_missing_comma_details() -> None:
    reply = '{"tasks": [{"id": "T1" "title": "x"}]}'
    with pytest.raises(AgentExecutionError) as caught:
        parse_tasks(reply, _response(reply))
    details = caught.value.details
    assert details["replyChars"] == len(reply)
    assert details["finishReason"] == "stop"
    assert details["repairsAttempted"] == 0
    assert "parseError" in details
    assert len(details["excerpt"]) <= EXCERPT_MAX_CHARS
    assert '"title"' in details["excerpt"]


def test_task_parse_valid_reply_unchanged() -> None:
    reply = json.dumps(
        {
            "tasks": [
                {
                    "id": "T1",
                    "title": "Task",
                    "milestoneRef": "M1",
                    "description": "Do it",
                    "acceptanceCriteria": ["Done"],
                    "dependsOn": [],
                    "expectedFiles": ["src/task.py"],
                    "verificationHint": "Run tests",
                }
            ]
        }
    )
    tasks = parse_tasks(reply, _response(reply))
    assert [task.id for task in tasks] == ["T1"]
