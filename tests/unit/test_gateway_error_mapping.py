"""Gateway error classification: one table for both provider gateways.

Every HTTP status / transport failure must map to the documented
code with the documented retryable flag (see
``asf.integrations.retry``), permanent failures must not be retried
inside the gateway, and the backoff must honor ``Retry-After`` first
and full jitter second, capped at 60 seconds.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import pytest

from asf.contracts.models import ModelMessage, ModelRequest
from asf.integrations.gemini import GeminiModelGateway
from asf.integrations.openai_compatible import OpenAICompatibleGateway, UrlLibTransport
from asf.models.errors import ModelGatewayError

OK_OPENAI = {
    "choices": [{"message": {"content": "done"}, "finish_reason": "stop"}],
    "model": "gpt-x",
    "usage": {"prompt_tokens": 3, "completion_tokens": 2},
}
OK_GEMINI = {
    "candidates": [
        {
            "content": {"parts": [{"text": "done"}]},
            "finishReason": "STOP",
        }
    ],
    "modelVersion": "gemini-x",
    "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 2},
}


def _request() -> ModelRequest:
    return ModelRequest(messages=[ModelMessage(role="user", content="hi")])


class OpenAiTransport:
    """Outcomes: (status, headers, payload) tuples or exceptions."""

    def __init__(self, outcomes: list) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0

    def post(self, url, *, headers, body, timeout_seconds):  # noqa: ANN001, ANN202
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        status, response_headers, payload = outcome
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        return status, response_headers, raw


def _openai(transport: OpenAiTransport, **kwargs) -> OpenAICompatibleGateway:
    kwargs.setdefault("sleep", lambda _seconds: None)
    return OpenAICompatibleGateway(
        base_url="https://models.example.com/v1",
        model="gpt-x",
        api_key="<redacted>",
        transport=transport,
        **kwargs,
    )


class GeminiTransport:
    def __init__(self, outcomes: list) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0

    def post(self, url, *, headers, body, timeout_seconds, max_response_bytes):  # noqa: ANN001, ANN202
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        status, response_headers, payload = outcome
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        return status, response_headers, raw


def _gemini(transport: GeminiTransport, **kwargs) -> GeminiModelGateway:
    kwargs.setdefault("sleep", lambda _seconds: None)
    return GeminiModelGateway(
        model="gemini-x",
        api_key="<redacted>",
        transport=transport,
        **kwargs,
    )


def _gemini_error(status: str, message: str) -> dict:
    return {"error": {"status": status, "message": message}}


# -- the mapping table, both gateways --------------------------------

OPENAI_CASES = [
    (429, {}, "LLM_RATE_LIMITED", True),
    (401, {}, "LLM_AUTH_FAILED", False),
    (403, {}, "LLM_AUTH_FAILED", False),
    (
        400,
        {"error": {"code": "context_length_exceeded", "message": "too long"}},
        "LLM_CONTEXT_TOO_LONG",
        False,
    ),
    (
        400,
        {"error": {"message": "Maximum context length is 8192 tokens"}},
        "LLM_CONTEXT_TOO_LONG",
        False,
    ),
    (400, {"error": {"message": "bad field"}}, "LLM_BAD_REQUEST", False),
    (404, {"error": {"message": "no such model"}}, "LLM_BAD_REQUEST", False),
    (422, {"error": {"message": "unprocessable"}}, "LLM_BAD_REQUEST", False),
    (500, {}, "INTEGRATION_UNAVAILABLE", True),
    (503, {}, "INTEGRATION_UNAVAILABLE", True),
]

GEMINI_CASES = [
    (429, {}, "LLM_RATE_LIMITED", True),
    (401, {}, "LLM_AUTH_FAILED", False),
    (403, _gemini_error("PERMISSION_DENIED", "denied"), "LLM_AUTH_FAILED", False),
    (
        400,
        _gemini_error(
            "INVALID_ARGUMENT",
            "The input token count exceeds the maximum number of input tokens allowed (1048576)",
        ),
        "LLM_CONTEXT_TOO_LONG",
        False,
    ),
    (400, _gemini_error("INVALID_ARGUMENT", "bad field"), "LLM_BAD_REQUEST", False),
    (404, _gemini_error("NOT_FOUND", "no such model"), "LLM_BAD_REQUEST", False),
    (500, {}, "INTEGRATION_UNAVAILABLE", True),
    (503, {}, "INTEGRATION_UNAVAILABLE", True),
]


@pytest.mark.parametrize(("status", "payload", "code", "retryable"), OPENAI_CASES)
def test_openai_http_error_mapping(status, payload, code, retryable):  # noqa: ANN001, ANN201
    transport = OpenAiTransport([(status, {}, payload)])
    with pytest.raises(ModelGatewayError) as caught:
        _openai(transport, max_retries=0).complete(_request())
    assert caught.value.code == code
    assert caught.value.retryable is retryable
    assert caught.value.details["httpStatus"] == status


@pytest.mark.parametrize(("status", "payload", "code", "retryable"), GEMINI_CASES)
def test_gemini_http_error_mapping(status, payload, code, retryable):  # noqa: ANN001, ANN201
    transport = GeminiTransport([(status, {}, payload)])
    with pytest.raises(ModelGatewayError) as caught:
        _gemini(transport, max_retries=0).complete(_request())
    assert caught.value.code == code
    assert caught.value.retryable is retryable
    assert caught.value.details["httpStatus"] == status


def test_openai_transport_timeout_maps_to_llm_timeout(monkeypatch) -> None:  # noqa: ANN001
    def raise_timeout(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        raise TimeoutError("timed out")

    monkeypatch.setattr(urllib.request, "urlopen", raise_timeout)
    with pytest.raises(ModelGatewayError) as caught:
        UrlLibTransport().post(
            "https://models.example.com/v1/chat/completions",
            headers={},
            body=b"{}",
            timeout_seconds=1,
        )
    assert caught.value.code == "LLM_TIMEOUT"
    assert caught.value.retryable is True


def test_openai_transport_urlerror_timeout_reason_maps_to_llm_timeout(monkeypatch) -> None:  # noqa: ANN001
    def raise_url_timeout(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        raise urllib.error.URLError(TimeoutError("timed out"))

    monkeypatch.setattr(urllib.request, "urlopen", raise_url_timeout)
    with pytest.raises(ModelGatewayError) as caught:
        UrlLibTransport().post(
            "https://models.example.com/v1/chat/completions",
            headers={},
            body=b"{}",
            timeout_seconds=1,
        )
    assert caught.value.code == "LLM_TIMEOUT"


def test_openai_transport_connection_error_maps_to_unavailable(monkeypatch) -> None:  # noqa: ANN001
    def raise_refused(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", raise_refused)
    with pytest.raises(ModelGatewayError) as caught:
        UrlLibTransport().post(
            "https://models.example.com/v1/chat/completions",
            headers={},
            body=b"{}",
            timeout_seconds=1,
        )
    assert caught.value.code == "INTEGRATION_UNAVAILABLE"
    assert caught.value.retryable is True


def test_gemini_transport_timeout_maps_to_llm_timeout() -> None:
    transport = GeminiTransport([TimeoutError()])
    with pytest.raises(ModelGatewayError) as caught:
        _gemini(transport, max_retries=0).complete(_request())
    assert caught.value.code == "LLM_TIMEOUT"
    assert caught.value.retryable is True


def test_gemini_transport_failure_maps_to_unavailable() -> None:
    transport = GeminiTransport([urllib.error.URLError("refused")])
    with pytest.raises(ModelGatewayError) as caught:
        _gemini(transport, max_retries=0).complete(_request())
    assert caught.value.code == "INTEGRATION_UNAVAILABLE"


# -- permanent failures are not retried inside the gateway ------------


def test_openai_401_is_not_retried() -> None:
    transport = OpenAiTransport([(401, {}, {"error": {"message": "bad key"}})])
    sleeps: list[float] = []
    with pytest.raises(ModelGatewayError) as caught:
        _openai(transport, max_retries=2, sleep=sleeps.append).complete(_request())
    assert caught.value.code == "LLM_AUTH_FAILED"
    assert transport.calls == 1
    assert sleeps == []


def test_gemini_401_is_not_retried() -> None:
    transport = GeminiTransport([(401, {}, _gemini_error("UNAUTHENTICATED", "bad key"))])
    sleeps: list[float] = []
    with pytest.raises(ModelGatewayError) as caught:
        _gemini(transport, max_retries=2, sleep=sleeps.append).complete(_request())
    assert caught.value.code == "LLM_AUTH_FAILED"
    assert transport.calls == 1
    assert sleeps == []


# -- backoff: Retry-After first, then full jitter, capped at 60s ------


def _no_jitter_allowed(_lo: float, _hi: float) -> float:
    raise AssertionError("jitter must not be consulted when Retry-After is present")


def test_openai_retry_after_seconds_is_respected() -> None:
    transport = OpenAiTransport(
        [
            (429, {"retry-after": "7"}, {}),
            (200, {}, OK_OPENAI),
        ]
    )
    sleeps: list[float] = []
    gateway = _openai(
        transport,
        sleep=sleeps.append,
        rand=_no_jitter_allowed,
    )
    assert gateway.complete(_request()).content == "done"
    assert sleeps == [7.0]


def test_gemini_retry_after_seconds_is_respected() -> None:
    transport = GeminiTransport(
        [
            (429, {"retry-after": "3"}, {}),
            (200, {}, OK_GEMINI),
        ]
    )
    sleeps: list[float] = []
    gateway = _gemini(
        transport,
        sleep=sleeps.append,
        rand=_no_jitter_allowed,
    )
    assert gateway.complete(_request()).content == "done"
    assert sleeps == [3.0]


def test_openai_retry_after_http_date_is_respected() -> None:
    retry_at = datetime.now(timezone.utc) + timedelta(seconds=20)
    transport = OpenAiTransport(
        [
            (503, {"retry-after": format_datetime(retry_at)}, {}),
            (200, {}, OK_OPENAI),
        ]
    )
    sleeps: list[float] = []
    gateway = _openai(transport, sleep=sleeps.append, rand=_no_jitter_allowed)
    gateway.complete(_request())
    assert len(sleeps) == 1
    assert 15 < sleeps[0] <= 20


def test_retry_after_is_capped_at_sixty_seconds() -> None:
    transport = OpenAiTransport(
        [
            (429, {"retry-after": "3600"}, {}),
            (200, {}, OK_OPENAI),
        ]
    )
    sleeps: list[float] = []
    _openai(transport, sleep=sleeps.append, rand=_no_jitter_allowed).complete(
        _request(),
    )
    assert sleeps == [60.0]


def test_jitter_stays_within_the_exponential_envelope() -> None:
    # rand at the ceiling: delays equal the old fixed 1s, 2s backoff.
    transport = OpenAiTransport([(503, {}, {}), (503, {}, {}), (200, {}, OK_OPENAI)])
    sleeps: list[float] = []
    _openai(
        transport,
        sleep=sleeps.append,
        rand=lambda _lo, hi: hi,
    ).complete(_request())
    assert sleeps == [1.0, 2.0]

    # rand at the floor: full jitter may legitimately pick ~0.
    transport = OpenAiTransport([(503, {}, {}), (200, {}, OK_OPENAI)])
    sleeps = []
    _openai(
        transport,
        sleep=sleeps.append,
        rand=lambda lo, _hi: lo,
    ).complete(_request())
    assert sleeps == [0.0]


def test_jitter_is_capped_at_sixty_seconds() -> None:
    outcomes = [(503, {}, {})] * 8 + [(200, {}, OK_OPENAI)]
    transport = OpenAiTransport(outcomes)
    sleeps: list[float] = []
    _openai(
        transport,
        max_retries=8,
        sleep=sleeps.append,
        rand=lambda _lo, hi: hi,
    ).complete(_request())
    assert sleeps == [1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 60.0, 60.0]
