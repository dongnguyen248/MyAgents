"""The one way agents report an unusable model reply.

Every AI agent validates the model's output against its contract
(required sections, JSON shape, schema, scope). When the output
fails, the failure is reported through this helper so the platform
sees ONE policy everywhere:

- code ``LLM_INVALID_RESPONSE``, category ``LLM``;
- ``retryable=True`` — a malformed reply is a model behaviour, and a
  fresh attempt may well produce a valid one;
- whether a step actually retries is the orchestrator's decision: it
  retries only when the step's retry policy allows it (``retry_on``
  membership when a policy lists codes).

Before this helper existed, the fix/review agents reported these
failures as non-retryable while spec/plan/task/implement reported
them as retryable, so the same model behaviour cost a retry on one
step and killed the run on another.
"""

from __future__ import annotations

from typing import Any

from asf.agents.base import AgentExecutionError

__all__ = ["invalid_response"]


def invalid_response(
    message: str,
    *,
    details: dict[str, Any] | None = None,
) -> AgentExecutionError:
    """Builds the standard 'model reply unusable' agent error."""
    return AgentExecutionError(
        "LLM_INVALID_RESPONSE",
        message,
        category="LLM",
        retryable=True,
        details=details,
    )
