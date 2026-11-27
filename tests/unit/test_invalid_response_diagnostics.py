from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any, get_args, get_origin

import pytest

from asf.agents._shared.response_diagnostics import (
    EXCERPT_MAX_CHARS,
    ResponseEvidence,
    diagnostic_details,
    error_offset,
    excerpt_for,
    log_excerpt,
)
from asf.agents.artifact_review.prompts import ArtifactReviewContent
from asf.agents.artifact_review.prompts import Finding as ArtifactFinding
from asf.agents.base import AgentExecutionError
from asf.agents.review.prompts import Finding as ReviewFinding
from asf.agents.review.prompts import ReviewContent
from asf.agents.task.items import TaskContent, TaskItem
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


def test_diagnostic_details_never_carries_excerpt() -> None:
    text = '{"a": 1 "b": 2}'
    details = diagnostic_details(ResponseEvidence(text, "stop", offset=8))
    assert details == {"replyChars": len(text), "finishReason": "stop", "repairsAttempted": 0}


def test_excerpt_is_bounded_and_covers_offset() -> None:
    text = "word " * 80 + "NEEDLE" + " word" * 80
    offset = text.index("NEEDLE")
    excerpt = excerpt_for(ResponseEvidence(text, "stop", offset=offset))
    assert excerpt is not None
    assert len(excerpt) <= EXCERPT_MAX_CHARS
    assert "NEEDLE" in excerpt


def test_excerpt_redacts_runtime_built_secret() -> None:
    secret = "".join(chr(97 + (i % 26)) for i in range(32))
    text = "x" * 120 + f' api_key = "{secret}" ' + "y" * 120
    offset = text.index(secret)
    excerpt = excerpt_for(ResponseEvidence(text, "stop", offset=offset))
    assert excerpt is not None
    assert secret not in excerpt
    assert "[REDACTED]" in excerpt


def test_log_excerpt_writes_marker_with_ids(caplog: pytest.LogCaptureFixture) -> None:
    marker = "untrusted-parser-diagnostic-marker"
    text = '{"findings": [' + marker
    evidence = ResponseEvidence(text, "stop", offset=text.index(marker))
    with caplog.at_level(logging.WARNING):
        log_excerpt(evidence, task_id="task-1", request_id="request-1")
    messages = [record.getMessage() for record in caplog.records]
    assert any(marker in message for message in messages)
    assert any("task=task-1" in message and "request=request-1" in message for message in messages)


def test_log_excerpt_escapes_newlines(caplog: pytest.LogCaptureFixture) -> None:
    text = '{"a": 1\n"b": 2}'
    evidence = ResponseEvidence(text, "stop", offset=text.index('"b"'))
    with caplog.at_level(logging.WARNING):
        log_excerpt(evidence, task_id="task-1", request_id="request-1")
    messages = [record.getMessage() for record in caplog.records]
    assert messages
    assert all("\n" not in message for message in messages)
    assert any("\\n" in message for message in messages)


def test_task_parse_missing_comma_details() -> None:
    reply = '{"tasks": [{"id": "T1" "title": "x"}]}'
    with pytest.raises(AgentExecutionError) as caught:
        parse_tasks(reply, _response(reply))
    details = caught.value.details
    assert details["replyChars"] == len(reply)
    assert details["finishReason"] == "stop"
    assert details["repairsAttempted"] == 0
    assert "parseError" in details
    assert "excerpt" not in details
    assert "input_value" not in details["parseError"]


def test_task_parse_error_excludes_input_value() -> None:
    secret = "".join(chr(97 + (i % 26)) for i in range(32))
    reply = json.dumps({"tasks": f"api_key={secret}"})
    with pytest.raises(AgentExecutionError) as caught:
        parse_tasks(reply, _response(reply))
    details = caught.value.details
    assert "parseError" in details
    assert secret not in details["parseError"]
    assert "input_value" not in details["parseError"]


def _task_reply(task: dict) -> str:
    return json.dumps({"tasks": [task]})


def _valid_task() -> dict:
    return {
        "id": "T1",
        "title": "Task",
        "milestoneRef": "M1",
        "description": "Do it",
        "acceptanceCriteria": ["Done"],
        "verificationHint": "Run tests",
    }


def _parse_error(reply: str) -> AgentExecutionError:
    with pytest.raises(AgentExecutionError) as caught:
        parse_tasks(reply, _response(reply))
    return caught.value


def test_task_model_chosen_extra_key_stays_out_of_parse_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    marker = "untrusted-parser-diagnostic-marker"
    task = _valid_task()
    task[marker] = 1
    with caplog.at_level(logging.WARNING):
        error = _parse_error(_task_reply(task))
    assert error.details["parseError"] == "tasks.0: extra_forbidden"
    assert marker not in error.message
    assert all(marker not in str(value) for value in error.details.values())
    assert marker not in caplog.text


def test_task_marker_id_stays_out_of_parse_error(caplog: pytest.LogCaptureFixture) -> None:
    marker = "untrusted-parser-diagnostic-marker"
    task = _valid_task()
    task["id"] = marker
    with caplog.at_level(logging.WARNING):
        error = _parse_error(_task_reply(task))
    assert error.details["parseError"] == "tasks.0.id: value_error"
    assert marker not in error.message
    assert all(marker not in str(value) for value in error.details.values())
    assert marker not in caplog.text


def test_task_long_id_parse_error_is_capped(caplog: pytest.LogCaptureFixture) -> None:
    marker = "untrusted-parser-diagnostic-marker"
    task = _valid_task()
    task["id"] = marker + "x" * 1500
    with caplog.at_level(logging.WARNING):
        error = _parse_error(_task_reply(task))
    assert len(error.details["parseError"]) <= 400
    assert marker not in error.details["parseError"]
    assert marker not in caplog.text


def test_task_secret_shaped_id_stays_out_of_parse_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "api_key=" + "".join(chr(97 + (i % 26)) for i in range(32))
    task = _valid_task()
    task["id"] = secret
    with caplog.at_level(logging.WARNING):
        error = _parse_error(_task_reply(task))
    assert error.details["parseError"] == "tasks.0.id: value_error"
    assert secret not in error.message
    assert all(secret not in str(value) for value in error.details.values())
    assert secret not in caplog.text


def _annotation_has_mapping(annotation: Any) -> bool:
    if get_origin(annotation) in (dict, Mapping):
        return True
    return any(_annotation_has_mapping(arg) for arg in get_args(annotation))


def test_reply_schemas_have_no_dict_fields() -> None:
    models = [
        ReviewContent,
        ReviewFinding,
        ArtifactReviewContent,
        ArtifactFinding,
        TaskContent,
        TaskItem,
    ]
    for model in models:
        for name, field in model.model_fields.items():
            assert not _annotation_has_mapping(field.annotation), (
                f"{model.__name__}.{name} is a dict field: a dict field lets "
                "error locations carry model-chosen keys, so safe_location "
                "must be revisited before this field is allowed"
            )


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
