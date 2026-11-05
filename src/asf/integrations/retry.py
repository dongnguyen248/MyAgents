"""Shared HTTP error mapping and backoff policy for model gateways.

Both provider gateways (OpenAI-compatible and Gemini) classify HTTP
failures with the same table and wait between retries with the same
policy, so a provider behaviour means the same thing — and costs the
same delay — no matter which adapter ASF is configured with:

- 429                       -> LLM_RATE_LIMITED (retryable)
- timeout                   -> LLM_TIMEOUT (retryable; raised locally)
- connection error, 5xx     -> INTEGRATION_UNAVAILABLE (retryable)
- 401 / 403                 -> LLM_AUTH_FAILED (permanent)
- 400 about context length  -> LLM_CONTEXT_TOO_LONG (permanent)
- any other 4xx             -> LLM_BAD_REQUEST (permanent)

LLM_INVALID_RESPONSE is deliberately absent from the table: it means
"a reply arrived but was unusable", never an HTTP failure.

Backoff: a provider's ``Retry-After`` hint wins when present;
otherwise full-jitter exponential backoff ``U(0, 2**attempt)``. Every
in-gateway delay is capped at ``MAX_BACKOFF_SECONDS`` — the
orchestrator's own retry policy owns longer waits.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

__all__ = [
    "MAX_BACKOFF_SECONDS",
    "backoff_delay",
    "http_error_code",
    "is_context_too_long",
    "parse_retry_after",
]

MAX_BACKOFF_SECONDS = 60.0

# Provider wordings that mark a 400 as "the request does not fit the
# model's context window" rather than a generically bad request.
_CONTEXT_MARKERS = (
    "context_length_exceeded",
    "context length",
    "maximum context",
    "context window",
    "input token count exceeds",
    "exceeds the maximum number of input tokens",
)


def http_error_code(status: int, *, context_too_long: bool = False) -> str:
    """Maps an HTTP failure status to a gateway error code."""
    if status == 429:
        return "LLM_RATE_LIMITED"
    if status in (401, 403):
        return "LLM_AUTH_FAILED"
    if status == 400 and context_too_long:
        return "LLM_CONTEXT_TOO_LONG"
    if status >= 500:
        return "INTEGRATION_UNAVAILABLE"
    return "LLM_BAD_REQUEST"


def is_context_too_long(*texts: str | None) -> bool:
    """True when a provider error code/message blames context length."""
    blob = " ".join(text for text in texts if text).lower()
    return any(marker in blob for marker in _CONTEXT_MARKERS)


def parse_retry_after(
    headers: Mapping[str, str], *, now: datetime | None = None,
) -> float | None:
    """Seconds from a Retry-After header (delay or HTTP-date), if any.

    Header lookup is case-insensitive. Unparseable values yield None
    (the caller falls back to computed backoff), as do dates in the
    past (clamped to 0 by the caller-visible result).
    """
    value: str | None = None
    for key, candidate in headers.items():
        if key.lower() == "retry-after":
            value = candidate
            break
    if value is None:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        moment = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    return max(0.0, (moment - current).total_seconds())


def backoff_delay(
    attempt: int,
    *,
    retry_after: float | None,
    rand: Callable[[float, float], float],
) -> float:
    """Delay before retry ``attempt`` (0-based).

    The provider's own hint wins and is trusted up to the cap;
    otherwise full jitter spreads concurrent callers over
    ``U(0, 2**attempt)`` so a recovering provider is not hit by a
    synchronized retry wave.
    """
    if retry_after is not None:
        return min(max(retry_after, 0.0), MAX_BACKOFF_SECONDS)
    ceiling = min(MAX_BACKOFF_SECONDS, float(2**attempt))
    return rand(0.0, ceiling)
