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


def run_code_generation(
    *,
    gateway: ModelGateway,
    request: ModelRequest,
    parse: Callable[[ModelResponse], ChangeSet],
    repair_attempts: int,
    format_name: str,
) -> tuple[ChangeSet, ModelUsage, int]:
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
    response = call_model(gateway, request)
    total_usage = response.usage
    repairs = 0
    while True:
        try:
            changeset = parse(response)
        except RepairableOutputError as error:
            if repairs >= repair_attempts:
                raise invalid_response(
                    error.message,
                    details={**error.details, "repairsAttempted": repairs},
                ) from None
            repairs += 1
            bad_reply = response.content[:MAX_REPAIR_REPLY_CHARS]
            repair_request = ModelRequest(
                messages=[
                    *request.messages,
                    ModelMessage(role="assistant", content=bad_reply),
                    ModelMessage(
                        role="user",
                        content=(
                            "Your previous reply was rejected:"
                            f" {error.model_message}\n"
                            f"Reply again with ONLY the corrected"
                            f" {format_name} output, complete and"
                            " self-contained, with no explanation."
                        ),
                    ),
                ],
                parameters=dict(request.parameters),
                model=request.model,
                metadata={**request.metadata, "repairAttempt": repairs},
            )
            response = call_model(gateway, repair_request)
            total_usage = _sum_usage(total_usage, response.usage)
            continue
        return changeset, total_usage, repairs


def summarize_validation_issues(issues: dict[str, Any]) -> str:
    """One short actionable line per validation issue kind."""
    parts: list[str] = []
    for key, value in issues.items():
        if key == "outOfScopePaths" and isinstance(value, list):
            parts.append(
                "paths outside the expected files list:"
                f" {', '.join(str(path) for path in value)}",
            )
        elif key == "missingPaths" and isinstance(value, list):
            names = ", ".join(
                str(item.get("path")) for item in value if isinstance(item, dict)
            )
            parts.append(f"files do not exist at the base ref: {names}")
        elif key == "deniedPaths" and isinstance(value, list):
            names = ", ".join(
                str(item.get("path")) for item in value if isinstance(item, dict)
            )
            parts.append(f"paths are never allowed: {names}")
        elif key == "contentIssues" and isinstance(value, list):
            rendered = "; ".join(
                f"{item.get('path')}: {item.get('issue')}"
                for item in value if isinstance(item, dict)
            )
            parts.append(f"content problems: {rendered}")
        elif key == "emptyChangeSet":
            parts.append("the change set is empty")
        else:
            parts.append(f"{key}: {value}")
    return "; ".join(parts) or "the change set failed validation"
