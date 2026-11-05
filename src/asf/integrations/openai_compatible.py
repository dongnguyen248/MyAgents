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
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any, Protocol

from asf.contracts.models import ModelRequest, ModelResponse, ModelUsage
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


class HttpTransport(Protocol):
    def post(
        self, url: str, *, headers: dict[str, str], body: bytes,
        timeout_seconds: float,
    ) -> tuple[int, bytes]:
        """POSTs and returns (status, body); HTTP errors are statuses."""
        ...


class UrlLibTransport:
    """Default transport (urllib)."""

    def post(
        self, url: str, *, headers: dict[str, str], body: bytes,
        timeout_seconds: float,
    ) -> tuple[int, bytes]:
        request = urllib.request.Request(
            url, data=body, headers=headers, method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise ModelGatewayError(
                "INTEGRATION_UNAVAILABLE",
                f"Model provider unreachable: {error}",
            ) from None


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

    def complete(self, request: ModelRequest) -> ModelResponse:
        model = request.model or self._model
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in request.messages
            ],
        }
        temperature = request.parameters.get("temperature")
        if isinstance(temperature, (int, float)) and not isinstance(temperature, bool):
            payload["temperature"] = temperature
        max_tokens = request.parameters.get("max_tokens")
        if (
            isinstance(max_tokens, bool) or not isinstance(max_tokens, int)
            or max_tokens <= 0
        ):
            max_tokens = DEFAULT_MAX_TOKENS
        payload["max_tokens"] = max_tokens
        status, raw = self._post_with_retries(payload)
        if status >= 400:
            detail = _provider_message(raw)
            code = (
                "INTEGRATION_UNAVAILABLE"
                if status == 429 or status >= 500
                else "LLM_INVALID_RESPONSE"
            )
            raise ModelGatewayError(
                code,
                f"Model provider error (HTTP {status})"
                + (f": {detail}" if detail else ""),
                details={"httpStatus": status},
            )
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
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError,
                TypeError, ValueError) as error:
            raise ModelGatewayError(
                "LLM_INVALID_RESPONSE",
                f"Model provider returned an unexpected response: {error}",
            ) from None

    def _post_with_retries(self, payload: dict[str, Any]) -> tuple[int, bytes]:
        """POST, retrying transient failures with exponential backoff.

        Transport errors (timeouts, unreachable host) and HTTP 429/5xx
        are transient by nature; everything else returns at once. After
        the retries run out, the last transport error is re-raised, or
        the last error status is returned for the caller to report.
        """
        body = json.dumps(payload).encode("utf-8")
        retries = 0
        while True:
            try:
                status, raw = self._transport.post(
                    f"{self._base}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    body=body,
                    timeout_seconds=self._timeout,
                )
            except ModelGatewayError:
                if retries >= self._max_retries:
                    raise
                self._sleep(2**retries)
                retries += 1
                continue
            if (status == 429 or status >= 500) and retries < self._max_retries:
                self._sleep(2**retries)
                retries += 1
                continue
            return status, raw


def _provider_message(body: bytes) -> str:
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return ""
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return error["message"]
        if isinstance(data.get("message"), str):
            return data["message"]
    return ""
