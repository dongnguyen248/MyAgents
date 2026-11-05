"""One checked model call for every AI agent.

Agents used to call the gateway and parse whatever came back: a
reply cut off by the output token limit (``finish_reason`` of
``length`` / ``MAX_TOKENS``) was fed to the parser, failed there as
a generic invalid response, and cost a full orchestrator step
retry with the identical prompt. This helper is the single place
that interprets ``finish_reason`` across providers:

- OpenAI-style: ``stop`` / ``length`` / ``content_filter``;
- Gemini-style: ``STOP`` / ``MAX_TOKENS`` / ``SAFETY`` / ...

A length-truncated reply raises ``LLM_OUTPUT_TRUNCATED``
(retryable, with the remedy in the message) and is NEVER parsed.
A provider-blocked reply (safety / content filter) raises the
shared invalid-response error: parsing a refusal is pointless.
Anything else returns the response untouched.
"""

from __future__ import annotations

from typing import Literal

from asf.agents._shared.model_errors import invalid_response
from asf.contracts.models import ModelRequest, ModelResponse
from asf.models.errors import ModelGatewayError
from asf.models.ports import ModelGateway

__all__ = [
    "FinishKind",
    "call_model",
    "classify_finish_reason",
    "ensure_complete",
]

FinishKind = Literal["ok", "truncated", "blocked"]

_TRUNCATED = {"length", "max_tokens", "MAX_TOKENS"}
_BLOCKED = {
    "content_filter",
    "safety",
    "SAFETY",
    "RECITATION",
    "BLOCKLIST",
    "PROHIBITED_CONTENT",
    "SPAM",
    "IMAGE_SAFETY",
    "MALFORMED_FUNCTION_CALL",
}


def classify_finish_reason(finish_reason: str) -> FinishKind:
    """Normalizes provider finish reasons into three buckets."""
    if finish_reason in _TRUNCATED:
        return "truncated"
    if finish_reason in _BLOCKED:
        return "blocked"
    return "ok"


def ensure_complete(response: ModelResponse) -> ModelResponse:
    """Applies the finish-reason policy to an already-made call."""
    kind = classify_finish_reason(response.finish_reason)
    if kind == "truncated":
        raise ModelGatewayError(
            "LLM_OUTPUT_TRUNCATED",
            "Model output was cut off by the output token limit"
            f" (finish_reason={response.finish_reason!r}); the reply"
            " is incomplete and was not parsed. Increase max_tokens"
            " or split the task into smaller items.",
            details={
                "finishReason": response.finish_reason,
                "model": response.model,
                "completionTokens": response.usage.completion_tokens,
            },
        )
    if kind == "blocked":
        raise invalid_response(
            "Model response was blocked by the provider"
            f" (finish_reason={response.finish_reason!r})",
            details={
                "finishReason": response.finish_reason,
                "model": response.model,
            },
        )
    return response


def call_model(gateway: ModelGateway, request: ModelRequest) -> ModelResponse:
    """Calls the gateway and applies the finish-reason policy."""
    return ensure_complete(gateway.complete(request))
