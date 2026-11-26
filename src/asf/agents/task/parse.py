from __future__ import annotations

from asf.agents._shared.model_errors import invalid_response
from asf.agents._shared.response_diagnostics import (
    diagnostic_details,
    error_offset,
    evidence_for,
)
from asf.agents.task.items import TaskContent, TaskItem
from asf.contracts.models import ModelResponse

__all__ = ["parse_tasks"]


def parse_tasks(reply: str, response: ModelResponse) -> list[TaskItem]:
    try:
        task_data = TaskContent.model_validate_json(reply)
    except Exception as error:
        evidence = evidence_for(response, offset=error_offset(error, reply), excerpt_text=reply)
        raise invalid_response(
            "Model response is not valid task JSON",
            details=diagnostic_details(evidence, {"parseError": str(error)}),
        ) from None
    return task_data.tasks
