"""Provider finish reasons, normalized into three buckets.

The vocabulary every gateway adapter must translate into:

- OpenAI-style: ``stop`` / ``length`` / ``content_filter``;
- Gemini-style: ``STOP`` / ``MAX_TOKENS`` / ``SAFETY`` / ...

Lives in the models layer (below the agents) because both the
agent-side call helper and the gateway-side map tap classify
responses, and neither may import the other.
"""

from __future__ import annotations

from typing import Literal

__all__ = ["FinishKind", "classify_finish_reason"]

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
