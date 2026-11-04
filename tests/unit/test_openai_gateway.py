"""OpenAI-compatible gateway against a fake transport."""

from __future__ import annotations

import json

import pytest

from asf.contracts.models import ModelMessage, ModelRequest
from asf.integrations.openai_compatible import OpenAICompatibleGateway
from asf.models.errors import ModelGatewayError


class FakeTransport:
    def __init__(self, status: int, payload: object) -> None:
        self.status = status
        self.payload = payload
        self.calls: list[dict] = []

    def post(self, url, *, headers, body, timeout_seconds):  # noqa: ANN001, ANN202
        self.calls.append({
            "url": url, "headers": headers, "body": json.loads(body),
        })
        raw = self.payload if isinstance(self.payload, bytes) else json.dumps(
            self.payload,
        ).encode()
        return self.status, raw


def _request() -> ModelRequest:
    return ModelRequest(messages=[
        ModelMessage(role="system", content="You write specs."),
        ModelMessage(role="user", content="A calculator"),
    ])


def _gateway(transport: FakeTransport) -> OpenAICompatibleGateway:
    return OpenAICompatibleGateway(
        base_url="https://models.example.com/v1/", model="gpt-x",
        api_key="secret-key", transport=transport,
    )


def test_complete_posts_chat_and_parses_response():
    transport = FakeTransport(200, {
        "model": "gpt-x-2026",
        "choices": [{
            "message": {"role": "assistant", "content": "# SPEC\n..."},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 12, "completion_tokens": 34},
    })
    response = _gateway(transport).complete(_request())
    assert response.content == "# SPEC\n..."
    assert response.model == "gpt-x-2026"
    assert response.usage.prompt_tokens == 12
    assert response.usage.completion_tokens == 34
    (call,) = transport.calls
    assert call["url"] == "https://models.example.com/v1/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer secret-key"
    assert call["body"]["model"] == "gpt-x"
    assert call["body"]["messages"][1] == {"role": "user", "content": "A calculator"}


def test_request_model_and_temperature_pass_through():
    transport = FakeTransport(200, {
        "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
    })
    request = ModelRequest(
        messages=[ModelMessage(role="user", content="hi")],
        model="other-model", parameters={"temperature": 0.2},
    )
    _gateway(transport).complete(request)
    assert transport.calls[0]["body"]["model"] == "other-model"
    assert transport.calls[0]["body"]["temperature"] == 0.2


def test_http_errors_map_to_gateway_errors():
    transport = FakeTransport(401, {"error": {"message": "bad key"}})
    with pytest.raises(ModelGatewayError) as caught:
        _gateway(transport).complete(_request())
    assert caught.value.code == "LLM_INVALID_RESPONSE"
    assert "bad key" in caught.value.message

    transport = FakeTransport(503, {"error": {"message": "down"}})
    with pytest.raises(ModelGatewayError) as caught:
        _gateway(transport).complete(_request())
    assert caught.value.code == "INTEGRATION_UNAVAILABLE"


def test_malformed_response_is_an_invalid_response_error():
    transport = FakeTransport(200, {"unexpected": True})
    with pytest.raises(ModelGatewayError) as caught:
        _gateway(transport).complete(_request())
    assert caught.value.code == "LLM_INVALID_RESPONSE"


def test_constructor_validation():
    with pytest.raises(ValueError):
        OpenAICompatibleGateway(base_url="ftp://x", model="m", api_key="k")
    with pytest.raises(ValueError):
        OpenAICompatibleGateway(base_url="https://x", model=" ", api_key="k")
    with pytest.raises(ValueError):
        OpenAICompatibleGateway(base_url="https://x", model="m", api_key="")
