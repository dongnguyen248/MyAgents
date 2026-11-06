"""The in-conversation repair loop for code-generating agents.

When an implement/fix reply fails to parse or validate, the step
used to die (or be retried by the orchestrator with the IDENTICAL
prompt, which reliably reproduced the identical mistake). The
repair loop instead continues the SAME conversation once: the
model sees its own bad reply plus a short, specific, actionable
error and answers again. One extra call is a fraction of the cost
of a full step retry — and unlike a step retry it can actually
fix the mistake.

Policy:

- at most ``repair_attempts`` extra calls (config, default 1);
- only :class:`RepairableOutputError` failures are repaired
  (block/JSON syntax, SEARCH mismatches, out-of-scope paths,
  missing files, empty change sets);
- truncation (``LLM_OUTPUT_TRUNCATED``) and secret findings are
  NEVER repaired — the first can only be fixed by a bigger token
  budget or a smaller task, the second must not be negotiated
  with the model;
- usage of every call is summed and returned with the repair
  count, so cost accounting stays honest.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from asf.agents._shared.model_call import call_model
from asf.agents._shared.model_errors import invalid_response
from asf.contracts.models import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelUsage,
)
from asf.models.ports import ModelGateway
from asf.tools.changeset import ChangeSet

__all__ = [
    "CodeGenerationCall",
    "RepairableOutputError",
    "run_code_generation",
    "summarize_validation_issues",
]

# The bad reply is echoed back truncated: enough for the model to
# see what it produced, bounded so the repair call stays cheap.
MAX_REPAIR_REPLY_CHARS = 8000


class RepairableOutputError(Exception):
    """A parse/validation failure the model can plausibly fix.

    ``message`` is the canonical agent-facing error text (kept
    stable: the orchestrator feeds it to later attempts verbatim);
    ``model_message`` is what the repair prompt shows the model —
    short, specific, actionable. ``details`` rides into the final
    agent error when the repair attempts run out.
    """

    def __init__(
        self,
        message: str,
        *,
        model_message: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.model_message = model_message or message
        self.details = dict(details or {})


def _sum_usage(total: ModelUsage, extra: ModelUsage) -> ModelUsage:
    return ModelUsage(
        prompt_tokens=total.prompt_tokens + extra.prompt_tokens,
        completion_tokens=total.completion_tokens + extra.completion_tokens,
    )


@dataclass(frozen=True)
class CodeGenerationCall:
    gateway: ModelGateway
    request: ModelRequest
    parse: Callable[[ModelResponse], ChangeSet]
    repair_attempts: int
    format_name: str


def run_code_generation(call: CodeGenerationCall) -> tuple[ChangeSet, ModelUsage, int]:
    """Calls the model and parses, repairing in-conversation.

    ``parse`` receives the full response (content + finish reason)
    and returns the validated ChangeSet for it; it raises
    :class:`RepairableOutputError` for fixable failures, and any
    other exception (notably the shared invalid_response error for
    secret findings) propagates immediately without repair.

    Returns (changeset, total usage across all calls, repairs used).
    When repairs run out, the last repairable failure becomes the
    standard invalid-response agent error.
    """
    request = call.request
    response = call_model(call.gateway, request)
    total_usage = response.usage
    repairs = 0
    while True:
        try:
            changeset = call.parse(response)
        except RepairableOutputError as error:
            if repairs >= call.repair_attempts:
                raise invalid_response(
                    error.message,
                    details={**error.details, "repairsAttempted": repairs},
                ) from None
            repairs += 1
            repair_request = _repair_request(call, response, error, repairs)
            response = call_model(call.gateway, repair_request)
            total_usage = _sum_usage(total_usage, response.usage)
            continue
        return changeset, total_usage, repairs


def _repair_request(
    call: CodeGenerationCall,
    response: ModelResponse,
    error: RepairableOutputError,
    attempt: int,
) -> ModelRequest:
    request = call.request
    bad_reply = response.content[:MAX_REPAIR_REPLY_CHARS]
    return ModelRequest(
        messages=[
            *request.messages,
            ModelMessage(role="assistant", content=bad_reply),
            ModelMessage(
                role="user",
                content=(
                    "Your previous reply was rejected:"
                    f" {error.model_message}\n"
                    f"Reply again with ONLY the corrected"
                    f" {call.format_name} output, complete and"
                    " self-contained, with no explanation."
                ),
            ),
        ],
        parameters=dict(request.parameters),
        model=request.model,
        metadata={**request.metadata, "repairAttempt": attempt},
    )


def summarize_validation_issues(issues: dict[str, Any]) -> str:
    """One short actionable line per validation issue kind."""
    parts = [_issue_line(key, value) for key, value in issues.items()]
    return "; ".join(parts) or "the change set failed validation"


def _issue_line(key: str, value: Any) -> str:
    formatter = _LIST_FORMATTERS.get(key)
    if formatter is not None and isinstance(value, list):
        return formatter(value)
    if key == "emptyChangeSet":
        return "the change set is empty"
    return f"{key}: {value}"


def _path_names(value: list[Any]) -> str:
    return ", ".join(str(item.get("path")) for item in value if isinstance(item, dict))


def _out_of_scope_line(value: list[Any]) -> str:
    joined = ", ".join(str(path) for path in value)
    return f"paths outside the expected files list: {joined}"


def _missing_line(value: list[Any]) -> str:
    return f"files do not exist at the base ref: {_path_names(value)}"


def _denied_line(value: list[Any]) -> str:
    return f"paths are never allowed: {_path_names(value)}"


def _content_line(value: list[Any]) -> str:
    rendered = "; ".join(
        f"{item.get('path')}: {item.get('issue')}" for item in value if isinstance(item, dict)
    )
    return f"content problems: {rendered}"


_LIST_FORMATTERS = {
    "outOfScopePaths": _out_of_scope_line,
    "missingPaths": _missing_line,
    "deniedPaths": _denied_line,
    "contentIssues": _content_line,
}
