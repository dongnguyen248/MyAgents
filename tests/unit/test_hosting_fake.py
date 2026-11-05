"""Shared fake transport for the hosting adapter tests."""

from __future__ import annotations

import json
from typing import Any

from asf.integrations.hosting.http import HttpResponse


class FakeTransport:
    """Records requests and answers from routes added in order."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._routes: list[tuple[str, str, int, Any]] = []

    def add(self, method: str, needle: str, payload: Any, status: int = 200) -> None:
        self._routes.append((method, needle, status, payload))

    def __call__(self, method, url, headers, body):  # noqa: ANN001, ANN202
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "body": json.loads(body) if body else None,
            }
        )
        # Routes are consumed in order, so a test can script a sequence
        # of responses for repeated calls to the same endpoint.
        for index, (route_method, needle, status, payload) in enumerate(self._routes):
            if route_method == method and needle in url:
                del self._routes[index]
                return HttpResponse(
                    status,
                    json.dumps(payload).encode("utf-8"),
                )
        raise AssertionError(f"Unexpected transport call: {method} {url}")

    def calls_to(self, needle: str) -> list[dict[str, Any]]:
        return [call for call in self.calls if needle in call["url"]]
