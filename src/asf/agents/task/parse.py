from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from asf.agents._shared.model_errors import invalid_response
from asf.agents._shared.response_diagnostics import (
    diagnostic_details,
    error_offset,
    evidence_for,
    log_excerpt,
)
from asf.agents._shared.security import redact_text
from asf.agents.task.items import TaskContent, TaskItem
from asf.contracts.models import AgentRequest, ModelResponse

__all__ = ["parse_tasks"]


def parse_tasks(
    reply: str, response: ModelResponse, request: AgentRequest | None = None
) -> list[TaskItem]:
    try:
        task_data = TaskContent.model_validate_json(reply)
    except Exception as error:
        evidence = evidence_for(response, offset=error_offset(error, reply), excerpt_text=reply)
        if request is not None:
            log_excerpt(evidence, task_id=request.task_id, request_id=request.request_id)
        raise invalid_response(
            "Model response is not valid task JSON",
            details=diagnostic_details(evidence, {"parseError": _parse_error_text(error)}),
        ) from None
    return task_data.tasks


def _parse_error_text(error: Exception) -> str:
    if isinstance(error, ValidationError):
        return "; ".join(_entry_text(entry) for entry in error.errors(include_input=False))
    if isinstance(error, json.JSONDecodeError):
        return str(error)
    return redact_text(str(error))


def _entry_text(entry: Mapping[str, Any]) -> str:
    location = ".".join(str(part) for part in entry.get("loc", ())) or "(root)"
    return f"{location}: {entry.get('msg', '')}"
