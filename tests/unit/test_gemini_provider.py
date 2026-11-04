from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from asf.contracts.models import ModelMessage, ModelRequest
from asf.integrations.gemini import (
    EvidenceCapture,
    GeminiModelGateway,
    RequestBudget,
)
from asf.models.errors import ModelGatewayError
from scripts.gemini_smoke import build_gateway
from tests.unit._fake_secrets import fake_secret


class FakeTransport:
    def __init__(self, outcomes: list[tuple[int, bytes] | Exception]) -> None:
        self.outcomes = outcomes
        self.calls: list[dict[str, Any]] = []

    def post(self, url, *, headers, body, timeout_seconds, max_response_bytes):
        self.calls.append(
            {
                "url": url,
                "headers": dict(headers),
                "body": body,
                "timeout": timeout_seconds,
                "max_response_bytes": max_response_bytes,
            }
        )
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def request(text: str = "hello") -> ModelRequest:
    return ModelRequest(
        messages=[ModelMessage(role="user", content=text)],
        metadata={"agentId": "agent-test"},
    )


def response_payload(text: str = "hi") -> bytes:
    return json.dumps(
        {
            "candidates": [
                {
                    "content": {"parts": [{"text": text}]},
                    "finishReason": "STOP",
                }
            ],
            "modelVersion": "configured-model",
            "usageMetadata": {
                "promptTokenCount": 2,
                "candidatesTokenCount": 3,
            },
        }
    ).encode()


def gateway(transport: FakeTransport, **kwargs: Any) -> GeminiModelGateway:
    model = kwargs.pop("model", "configured-model")
    return GeminiModelGateway(
        model=model,
        api_key="fake-secret-value",
        transport=transport,
        sleep=lambda _seconds: None,
        **kwargs,
    )


def test_success_maps_gemini_response_and_authenticates_with_header():
    transport = FakeTransport([(200, response_payload())])

    result = gateway(transport).complete(request())

    assert result.content == "hi"
    assert result.model == "configured-model"
    assert result.usage.prompt_tokens == 2
    assert result.usage.completion_tokens == 3
    assert transport.calls[0]["url"].endswith("/models/configured-model:generateContent")
    assert transport.calls[0]["headers"]["x-goog-api-key"] == "fake-secret-value"
    assert "fake-secret-value" not in transport.calls[0]["url"]


@pytest.mark.parametrize(
    ("outcome", "code"),
    [
        ((429, b"rate limited"), "LLM_RATE_LIMITED"),
        ((500, b"server error"), "INTEGRATION_UNAVAILABLE"),
        ((400, b"bad request"), "LLM_INVALID_RESPONSE"),
    ],
)
def test_http_error_mapping(outcome, code):
    transport = FakeTransport([outcome])

    with pytest.raises(ModelGatewayError) as raised:
        gateway(transport, max_retries=0).complete(request())

    assert raised.value.code == code
    assert "fake-secret-value" not in str(raised.value)


def test_timeout_retries_are_bounded():
    sleeps: list[float] = []
    transport = FakeTransport(
        [TimeoutError(), TimeoutError(), TimeoutError(), (200, response_payload())]
    )
    model_gateway = GeminiModelGateway(
        model="configured-model",
        api_key="fake-secret-value",
        transport=transport,
        sleep=sleeps.append,
        max_retries=2,
    )

    with pytest.raises(ModelGatewayError) as raised:
        model_gateway.complete(request())

    assert raised.value.code == "LLM_TIMEOUT"
    assert len(transport.calls) == 3
    assert sleeps == [1, 2]


def test_request_budget_counts_retries():
    transport = FakeTransport([(500, b"error"), (200, response_payload())])
    model_gateway = gateway(transport, max_requests_per_run=1, max_retries=2)

    with pytest.raises(ModelGatewayError) as raised:
        model_gateway.complete(request())

    assert raised.value.code == "INTEGRATION_UNAVAILABLE"
    assert len(transport.calls) == 1


def test_request_and_response_size_limits():
    transport = FakeTransport([(200, response_payload())])
    with pytest.raises(ModelGatewayError, match="request exceeds"):
        gateway(transport, max_request_bytes=1).complete(request())
    assert not transport.calls

    transport = FakeTransport([(200, b"x" * 11)])
    with pytest.raises(ModelGatewayError, match="response exceeds"):
        gateway(transport, max_response_bytes=10).complete(request())


def test_invalid_response_payload_maps_to_invalid_response():
    transport = FakeTransport([(200, b'{"candidates": []}')])

    with pytest.raises(ModelGatewayError) as raised:
        gateway(transport).complete(request())

    assert raised.value.code == "LLM_INVALID_RESPONSE"


def test_endpoint_allowlist_rejects_non_google_endpoints():
    transport = FakeTransport([])
    with pytest.raises(ValueError, match="approved Google API host"):
        GeminiModelGateway(
            model="configured-model",
            api_key="fake-secret-value",
            endpoint="http://example.test/v1beta",
            transport=transport,
        )


@pytest.mark.parametrize("model", ["", "  ", "models/gemini-3.8-flash"])
def test_model_id_validation_and_normalization(model: str):
    transport = FakeTransport([(200, response_payload())])
    if model.strip():
        model_gateway = gateway(transport, model=model)
        model_gateway.complete(request())
        assert transport.calls[0]["url"].endswith(
            "/models/gemini-3.8-flash:generateContent"
        )
    else:
        with pytest.raises(ValueError, match="non-empty ID"):
            gateway(transport, model=model)


def test_model_id_rejects_unsafe_characters():
    with pytest.raises(ValueError, match="letters"):
        gateway(FakeTransport([]), model="gemini/model")


@pytest.mark.parametrize(
    ("status", "provider_status"),
    [
        (401, "UNAUTHENTICATED"),
        (403, "PERMISSION_DENIED"),
        (404, "NOT_FOUND"),
        (400, "INVALID_ARGUMENT"),
    ],
)
def test_4xx_error_includes_redacted_provider_diagnostics(
    status: int, provider_status: str, tmp_path: Path
):
    api_key = fake_secret("aq")
    evidence = EvidenceCapture(tmp_path)
    body = json.dumps(
        {
            "error": {
                "status": provider_status,
                "message": f"bad request contains {api_key}",
            }
        }
    ).encode()
    with pytest.raises(ModelGatewayError) as raised:
        GeminiModelGateway(
            model="configured-model",
            api_key=api_key,
            transport=FakeTransport([(status, body)]),
            evidence=evidence,
            run_id="error-run",
            max_retries=2,
            sleep=lambda _seconds: None,
        ).complete(request(api_key))
    error = raised.value
    assert provider_status in str(error)
    assert "/v1beta/models/configured-model:generateContent" in str(error)
    assert api_key not in str(error)
    assert api_key not in repr(error)
    evidence_text = next(tmp_path.glob("*.jsonl")).read_text(encoding="utf-8")
    assert api_key not in evidence_text


def test_shared_request_budget_counts_across_gateways():
    budget = RequestBudget(limit=12)
    first_transport = FakeTransport([(500, b"error")] * 12)
    second_transport = FakeTransport([(200, response_payload())])
    first = gateway(first_transport, request_budget=budget, max_retries=20)
    second = gateway(second_transport, request_budget=budget)

    with pytest.raises(ModelGatewayError):
        first.complete(request())
    with pytest.raises(ModelGatewayError, match="budget exhausted"):
        second.complete(request())
    assert len(first_transport.calls) == 12
    assert not second_transport.calls


def test_redirect_response_is_not_followed():
    transport = FakeTransport([(302, b"redirect")])
    with pytest.raises(ModelGatewayError) as raised:
        gateway(transport, max_retries=0).complete(request())
    assert raised.value.code == "LLM_INVALID_RESPONSE"
    assert len(transport.calls) == 1


def test_smoke_gateway_wires_evidence_capture(tmp_path: Path):
    evidence = EvidenceCapture(tmp_path, secrets=["AQ.smoke-key-123456"])
    transport = FakeTransport([(200, response_payload())])
    smoke_gateway = build_gateway(
        "AQ.smoke-key-123456",
        "models/gemini-3.8-flash",
        evidence,
        transport,
    )

    smoke_gateway.complete(request())

    assert evidence.last_path is not None
    assert evidence.last_path.parent == tmp_path


def test_aq_key_is_redacted_from_evidence_errors_and_logs(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    api_key = fake_secret("aq")
    evidence = EvidenceCapture(tmp_path)
    transport = FakeTransport([(200, response_payload(api_key))])
    model_gateway = GeminiModelGateway(
        model="configured-model",
        api_key=api_key,
        transport=transport,
        evidence=evidence,
        run_id="run/one",
        sleep=lambda _seconds: None,
    )

    with caplog.at_level(logging.INFO):
        model_gateway.complete(request(api_key))

    files = list(tmp_path.glob("*.jsonl"))
    assert len(files) == 1
    content = files[0].read_text(encoding="utf-8")
    assert api_key not in content
    assert "[REDACTED]" in content
    record = json.loads(content)
    assert record["runId"] == "run/one"
    assert record["status"] == "success"
    assert record["retryCount"] == 0
    assert len(record["requestHash"]) == 64
    assert len(record["responseHash"]) == 64
    assert api_key not in caplog.text
    assert api_key not in repr(record)

    failing_transport = FakeTransport([OSError(f"provider rejected {api_key}")])
    failing_gateway = GeminiModelGateway(
        model="configured-model",
        api_key=api_key,
        transport=failing_transport,
        max_retries=0,
    )
    with pytest.raises(ModelGatewayError) as raised:
        failing_gateway.complete(request(api_key))
    assert api_key not in str(raised.value)
    assert api_key not in repr(raised.value)

    call = transport.calls[0]
    assert call["headers"] == {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    }
    assert api_key not in call["url"]
