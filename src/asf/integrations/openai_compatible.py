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
import urllib.error
import urllib.request
from typing import Any, Protocol

from asf.contracts.models import ModelRequest, ModelResponse, ModelUsage
from asf.models.errors import ModelGatewayError

__all__ = ["HttpTransport", "OpenAICompatibleGateway", "UrlLibTransport"]


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
        timeout_seconds: float = 120.0,
    ) -> None:
        if not base_url.startswith(("https://", "http://")):
            raise ValueError("Base URL must be an http(s) URL")
        if not model.strip():
            raise ValueError("Model must not be empty")
        if not api_key:
            raise ValueError("API key must not be empty")
        self._base = base_url.rstrip("/")
        self._model = model.strip()
        self._api_key = api_key
        self._transport = transport or UrlLibTransport()
        self._timeout = timeout_seconds

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
        status, raw = self._transport.post(
            f"{self._base}/chat/completions",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            body=json.dumps(payload).encode("utf-8"),
            timeout_seconds=self._timeout,
        )
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
