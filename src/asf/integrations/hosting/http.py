"""Minimal JSON-over-HTTPS transport for the hosting adapters.

Mirrors the urllib pattern of the Gemini integration: a small callable
transport (injectable, so tests never touch the network) plus a client
that builds requests, parses JSON, and normalizes HTTP failures into
:class:`~asf.integrations.hosting.ports.HostingError`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from asf.integrations.hosting.ports import HostingError

__all__ = ["HttpResponse", "Transport", "UrllibTransport", "JsonHttpClient"]


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes


class Transport(Protocol):
    def __call__(
        self, method: str, url: str, headers: Mapping[str, str], body: bytes | None,
    ) -> HttpResponse:
        ...


class UrllibTransport:
    """Real transport. Redirects are followed by urllib's default
    opener; timeouts bound every call."""

    def __init__(self, timeout_seconds: float = 30.0) -> None:
        self._timeout = timeout_seconds

    def __call__(
        self, method: str, url: str, headers: Mapping[str, str], body: bytes | None,
    ) -> HttpResponse:
        request = Request(
            url, data=body, method=method, headers=dict(headers),
        )
        try:
            with urlopen(request, timeout=self._timeout) as response:
                return HttpResponse(status=response.status, body=response.read())
        except HTTPError as error:
            return HttpResponse(status=error.code, body=error.read())
        except URLError as error:
            raise HostingError(
                f"Could not reach the hosting provider: {error.reason}",
                retryable=True,
            ) from None


class JsonHttpClient:
    """JSON requests against one provider API base URL."""

    def __init__(
        self,
        base_url: str,
        headers: Mapping[str, str],
        transport: Transport | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._headers = dict(headers)
        self._transport = transport or UrllibTransport()

    def request(
        self, method: str, path: str, payload: Mapping[str, Any] | None = None,
    ) -> Any:
        body = (
            json.dumps(dict(payload)).encode("utf-8") if payload is not None else None
        )
        headers = dict(self._headers)
        if body is not None:
            headers["Content-Type"] = "application/json"
        response = self._transport(method, self._base + path, headers, body)
        if response.status >= 400:
            raise HostingError(
                _error_message(response),
                status=response.status,
                retryable=response.status == 429 or response.status >= 500,
            )
        if not response.body:
            return None
        try:
            return json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise HostingError(
                f"Provider returned a non-JSON response (HTTP {response.status})",
                status=response.status,
            ) from None


def _error_message(response: HttpResponse) -> str:
    """Best-effort provider error text: GitLab uses ``message`` (string
    or one-key dict), GitHub uses ``message`` too."""
    try:
        data = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        data = None
    if isinstance(data, dict):
        message = data.get("message")
        if isinstance(message, str) and message:
            return f"Hosting provider error (HTTP {response.status}): {message}"
        if isinstance(message, dict) and message:
            key, values = next(iter(message.items()))
            return (
                f"Hosting provider error (HTTP {response.status}): "
                f"{key} {', '.join(str(v) for v in values)}"
            )
        errors = data.get("errors")
        if isinstance(errors, list) and errors:
            first = errors[0]
            if isinstance(first, dict) and first.get("message"):
                return (
                    f"Hosting provider error (HTTP {response.status}): "
                    f"{first['message']}"
                )
    return f"Hosting provider error (HTTP {response.status})"
