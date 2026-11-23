"""A transport wrapper that adds an operator's custom headers.

Per-agent connection profiles may carry extra headers (a proxy's
client id, a tenant marker). The provider gateways build their own
auth headers per request and take a transport, so the extra headers
are merged at the transport seam instead of inside each adapter:
the gateway's own headers win on a name clash, because the adapter
owns Authorization and Content-Type (profile validation also rejects
those names, this is defence in depth). The wrapper is duck-typed
against both provider transports - it forwards every other argument
(including Gemini's ``max_response_bytes``) untouched.
"""

from __future__ import annotations

from typing import Any


class HeaderInjectingTransport:
    """Wraps a provider HttpTransport, adding fixed extra headers."""

    def __init__(self, inner: Any, headers: dict[str, str]) -> None:
        self._inner = inner
        self._headers = dict(headers)

    def post(self, url: str, **kwargs: Any) -> Any:
        headers = dict(self._headers)
        headers.update(kwargs.get("headers") or {})
        kwargs["headers"] = headers
        return self._inner.post(url, **kwargs)
