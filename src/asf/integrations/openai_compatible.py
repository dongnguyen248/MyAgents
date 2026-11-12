"""OpenAI-compatible chat-completions gateway for the ModelGateway port.

One adapter covers every provider that speaks the OpenAI chat API:
OpenAI itself, GitHub Models (``https://models.github.ai/inference``,
authenticated with a GitHub token), and any custom/self-hosted
endpoint with the same shape. Note this is *not* the Muse
editor API — that is a separate OAuth-based surface with no stable
public contract; GitHub Models is the API-key route to GitHub-hosted
models.

The transport is injectable, so tests never touch the network.
"""

from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any, NoReturn, Protocol

from asf.agents._shared.security import redact_text
from asf.contracts.models import ModelRequest, ModelResponse, ModelUsage
from asf.integrations.retry import (
    backoff_delay,
    effective_timeout,
    http_error_code,
    is_context_too_long,
    is_model_not_supported,
    parse_retry_after,
)
from asf.models.errors import ModelGatewayError

__all__ = [
    "DEFAULT_MAX_TOKENS",
    "HttpTransport",
    "OpenAICompatibleGateway",
    "UrlLibTransport",
]

# Transient failures (timeouts, connection errors, HTTP 429/5xx) are
# retried with exponential backoff, mirroring the Gemini gateway: a
# momentary provider stall should cost seconds, not the agent step —
# through a session proxy, stalls of a few seconds are routine.
DEFAULT_MAX_RETRIES = 2

# Always send an explicit output cap. When the field is absent,
# providers — and especially session proxies such as Copilot's —
# apply their own small defaults, and long agent documents (specs,
# plans, changesets) come back truncated mid-document and fail the
# agents' output contracts. 16384 fits the output limits of every
# model ASF is used with; a request may override it via the
# ``max_tokens`` model parameter.
DEFAULT_MAX_TOKENS = 16384

# Cap for the provider's own error message when it is carried in
# error details (providerMessage): long enough to hold the actual
# diagnosis, short enough for a run record and a banner line.
_PROVIDER_MESSAGE_MAX = 240


class HttpTransport(Protocol):
    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> tuple[int, Mapping[str, str], bytes]:
        """POSTs and returns (status, headers, body).

        HTTP errors are statuses, not exceptions. Header names are
        lowercased so callers can look up e.g. ``retry-after``
        reliably.
        """
        ...


class UrlLibTransport:
    """Default transport (urllib)."""

    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> tuple[int, Mapping[str, str], bytes]:
        request = urllib.request.Request(
            url,
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                return (
                    response.status,
                    _lower_headers(response.headers),
                    response.read(),
                )
        except urllib.error.HTTPError as error:
            return error.code, _lower_headers(error.headers), error.read()
        except TimeoutError as error:
            raise ModelGatewayError(
                "LLM_TIMEOUT",
                f"Model provider timed out: {error}",
            ) from None
        except (urllib.error.URLError, OSError) as error:
            reason = getattr(error, "reason", None)
            if isinstance(reason, TimeoutError):
                raise ModelGatewayError(
                    "LLM_TIMEOUT",
                    f"Model provider timed out: {error}",
                ) from None
            raise ModelGatewayError(
                "INTEGRATION_UNAVAILABLE",
                f"Model provider unreachable: {error}",
            ) from None


def _lower_headers(headers: Any) -> dict[str, str]:
    if headers is None:
        return {}
    return {str(key).lower(): str(value) for key, value in headers.items()}


class OpenAICompatibleGateway:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        transport: HttpTransport | None = None,
        timeout_seconds: float = 300.0,
        max_retries: int = DEFAULT_MAX_RETRIES,
        sleep: Callable[[float], None] = time.sleep,
        rand: Callable[[float, float], float] = random.uniform,
        prompt_cache: bool = False,
    ) -> None:
        if not base_url.startswith(("https://", "http://")):
            raise ValueError("Base URL must be an http(s) URL")
        if not model.strip():
            raise ValueError("Model must not be empty")
        if not api_key:
            raise ValueError("API key must not be empty")
        if timeout_seconds <= 0 or max_retries < 0:
            raise ValueError("Timeout must be positive and retries non-negative")
        self._base = base_url.rstrip("/")
        self._model = model.strip()
        self._api_key = api_key
        self._transport = transport or UrlLibTransport()
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        self._sleep = sleep
        self._rand = rand
        # Prompt caching is opt-in per deployment: only endpoints
        # that understand Anthropic-style cache_control content
        # parts may receive them (the assembly enables this for
        # Anthropic-compatible base URLs). Everywhere else the
        # agents' cachePrefixMessages hint is ignored, as designed.
        self._prompt_cache = prompt_cache

    def complete(self, request: ModelRequest) -> ModelResponse:
        model = request.model or self._model
        prefix = 0
        if self._prompt_cache:
            hint = request.metadata.get("cachePrefixMessages")
            if isinstance(hint, int) and not isinstance(hint, bool) and hint > 0:
                prefix = min(hint, len(request.messages))
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {
                    "role": message.role,
                    "content": (
                        [
                            {
                                "type": "text",
                                "text": message.content,
                                "cache_control": {"type": "ephemeral"},
                            }
                        ]
                        if index < prefix
                        else message.content
                    ),
                }
                for index, message in enumerate(request.messages)
            ],
        }
        temperature = request.parameters.get("temperature")
        if isinstance(temperature, (int, float)) and not isinstance(temperature, bool):
            payload["temperature"] = temperature
        max_tokens = request.parameters.get("max_tokens")
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens <= 0:
            max_tokens = DEFAULT_MAX_TOKENS
        payload["max_tokens"] = max_tokens
        status, _headers, raw = self._post_with_retries(
            payload,
            timeout_seconds=effective_timeout(self._timeout, request),
        )
        if status >= 400:
            _raise_provider_error(status, raw)
        try:
            data = json.loads(raw.decode("utf-8"))
            choice = data["choices"][0]
            content = choice["message"]["content"]
            if not isinstance(content, str):
                raise TypeError("content is not a string")
            usage = data.get("usage") or {}
            return ModelResponse(
                content=content,
                model=str(data.get("model") or model),
                usage=ModelUsage(
                    prompt_tokens=int(usage.get("prompt_tokens", 0)),
                    completion_tokens=int(usage.get("completion_tokens", 0)),
                ),
                finish_reason=str(choice.get("finish_reason") or "stop"),
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            KeyError,
            IndexError,
            TypeError,
            ValueError,
        ) as error:
            raise ModelGatewayError(
                "LLM_INVALID_RESPONSE",
                f"Model provider returned an unexpected response: {error}",
            ) from None

    def _post_with_retries(
        self,
        payload: dict[str, Any],
        *,
        timeout_seconds: float,
    ) -> tuple[int, Mapping[str, str], bytes]:
        """POST, retrying transient failures with shared backoff.

        Retryable transport errors (timeout, unreachable host) and
        HTTP 429/5xx are transient by nature; everything else returns
        at once — a 401 will still be a 401 after a nap. Delays honor
        the provider's Retry-After header, else full-jitter
        exponential backoff (see asf.integrations.retry). After the
        retries run out, the last transport error is re-raised, or
        the last error status is returned for the caller to classify.
        """
        body = json.dumps(payload).encode("utf-8")
        retries = 0
        while True:
            try:
                status, headers, raw = self._transport.post(
                    f"{self._base}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    body=body,
                    timeout_seconds=timeout_seconds,
                )
            except ModelGatewayError as error:
                if not error.retryable or retries >= self._max_retries:
                    raise
                self._sleep(
                    backoff_delay(
                        retries,
                        retry_after=None,
                        rand=self._rand,
                    )
                )
                retries += 1
                continue
            if (status == 429 or status >= 500) and retries < self._max_retries:
                self._sleep(
                    backoff_delay(
                        retries,
                        retry_after=parse_retry_after(headers),
                        rand=self._rand,
                    )
                )
                retries += 1
                continue
            return status, headers, raw


def _provider_error(body: bytes) -> tuple[str, str]:
    """(message, code) from a provider error body; ("", "") if opaque."""
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "", ""
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            code = error.get("code")
            return (
                message if isinstance(message, str) else "",
                code if isinstance(code, str) else "",
            )
        if isinstance(data.get("message"), str):
            return data["message"], ""
    return "", ""


def _raise_provider_error(status: int, raw: bytes) -> NoReturn:
    """Raise the classified gateway error for a failed response.

    The provider's parsed code and message ride in the details
    (providerCode / providerMessage, the message redacted and
    capped): friendlier rewrites higher up replace the message
    text, and without the details the provider's own diagnosis
    would survive only in a log line. The raised message keeps
    the provider text after the status, redacted the same way.
    Classification still reads the unredacted text.
    """
    detail, provider_code = _provider_error(raw)
    safe = redact_text(detail)
    details: dict[str, Any] = {"httpStatus": status}
    if provider_code:
        details["providerCode"] = redact_text(provider_code)
    if safe:
        details["providerMessage"] = safe[:_PROVIDER_MESSAGE_MAX]
    raise ModelGatewayError(
        _error_code(status, provider_code, detail, raw),
        f"Model provider error (HTTP {status})" + (f": {safe}" if safe else ""),
        details=details,
    )


def _error_code(status: int, provider_code: str, detail: str, raw: bytes) -> str:
    """The gateway error code for a failed provider response.

    The raw body joins the model-marker scan: when the body is not
    the provider's usual JSON envelope the parsed code/message come
    back empty, while the wording that names the model id is still
    in the payload.
    """
    return http_error_code(
        status,
        context_too_long=is_context_too_long(provider_code, detail),
        model_not_supported=is_model_not_supported(
            provider_code,
            detail,
            raw.decode("utf-8", "replace"),
        ),
    )
