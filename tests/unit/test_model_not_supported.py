"""Unsupported-model failures: classification, non-retry, attribution.

FIX-1 continued, Stage 2. A provider's "this model id is unknown"
(observed as a generic LLM_BAD_REQUEST with a raw JSON body when
the Fix agent's stored model was the string "admin") is a distinct
non-retryable code, and the routing gateway rewrites it so the
operator sees the agent, the exact id sent, where the id came from
and which endpoint host rejected it — never any key material.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from asf.api.model_settings import ModelSettings, SettingsRoutingGateway, agent_key
from asf.contracts.models import ModelMessage, ModelRequest, ModelResponse, ModelUsage
from asf.integrations.openai_compatible import OpenAICompatibleGateway
from asf.integrations.retry import http_error_code, is_model_not_supported
from asf.models.errors import ModelGatewayError

UNSUPPORTED_BODY = {
    "error": {
        "message": "The requested model is not supported.",
        "code": "model_not_supported",
        "param": "model",
        "type": "invalid_request_error",
    }
}


class FakeTransport:
    def __init__(self, status: int, payload: object) -> None:
        self.status = status
        self.payload = payload
        self.calls = 0

    def post(self, url, *, headers, body, timeout_seconds):  # noqa: ANN001, ANN202
        self.calls += 1
        raw = self.payload if isinstance(self.payload, bytes) else json.dumps(self.payload).encode()
        return self.status, {}, raw


def _gateway(transport: FakeTransport) -> OpenAICompatibleGateway:
    return OpenAICompatibleGateway(
        base_url="https://models.example.com/v1/",
        model="gpt-x",
        api_key="test-key",
        transport=transport,
        sleep=lambda _: None,
    )


def _request(metadata: dict | None = None) -> ModelRequest:
    return ModelRequest(
        messages=[ModelMessage(role="user", content="hi")],
        metadata=metadata or {},
    )


def _classify(status: int, payload: object) -> ModelGatewayError:
    gateway = _gateway(FakeTransport(status, payload))
    with pytest.raises(ModelGatewayError) as caught:
        gateway.complete(_request())
    return caught.value


# ---------------------------------------------------------------------------
# classification
# ---------------------------------------------------------------------------


def test_json_model_not_supported_at_400_is_the_new_code() -> None:
    error = _classify(400, UNSUPPORTED_BODY)
    assert error.code == "LLM_MODEL_NOT_SUPPORTED"
    assert error.category == "LLM"
    assert error.retryable is False
    assert error.details == {
        "httpStatus": 400,
        "providerCode": "model_not_supported",
        "providerMessage": "The requested model is not supported.",
    }


def test_json_model_not_supported_at_404_is_the_new_code() -> None:
    error = _classify(404, UNSUPPORTED_BODY)
    assert error.code == "LLM_MODEL_NOT_SUPPORTED"
    assert error.details == {
        "httpStatus": 404,
        "providerCode": "model_not_supported",
        "providerMessage": "The requested model is not supported.",
    }


def test_provider_code_case_and_wording_variants() -> None:
    body = {"error": {"message": "Unknown model", "code": "Model_Not_Found"}}
    assert _classify(404, body).code == "LLM_MODEL_NOT_SUPPORTED"
    assert is_model_not_supported("MODEL NOT SUPPORTED")
    assert is_model_not_supported(None, "the model not found in this region")
    assert not is_model_not_supported("invalid_parameter", "bad temperature")


def test_non_json_body_still_classifies_from_the_raw_text() -> None:
    error = _classify(400, b"upstream error: model_not_supported for this key")
    assert error.code == "LLM_MODEL_NOT_SUPPORTED"


def test_truncated_json_body_still_classifies_from_the_raw_text() -> None:
    error = _classify(400, b'{"error":{"code":"model_not_supported","mess')
    assert error.code == "LLM_MODEL_NOT_SUPPORTED"


def test_a_different_400_stays_llm_bad_request() -> None:
    body = {"error": {"message": "Invalid temperature", "code": "invalid_parameter"}}
    error = _classify(400, body)
    assert error.code == "LLM_BAD_REQUEST"
    assert error.retryable is False


def test_a_404_without_model_markers_stays_llm_bad_request() -> None:
    body = {"error": {"message": "Deployment not found", "code": "not_found"}}
    assert _classify(404, body).code == "LLM_BAD_REQUEST"


def test_http_error_code_mapping() -> None:
    assert http_error_code(400, model_not_supported=True) == "LLM_MODEL_NOT_SUPPORTED"
    assert http_error_code(404, model_not_supported=True) == "LLM_MODEL_NOT_SUPPORTED"
    assert http_error_code(400) == "LLM_BAD_REQUEST"
    assert http_error_code(404) == "LLM_BAD_REQUEST"
    assert http_error_code(500, model_not_supported=True) == "INTEGRATION_UNAVAILABLE"


# ---------------------------------------------------------------------------
# non-retry
# ---------------------------------------------------------------------------


def test_model_not_supported_is_never_retried_by_the_gateway() -> None:
    transport = FakeTransport(400, UNSUPPORTED_BODY)
    with pytest.raises(ModelGatewayError):
        _gateway(transport).complete(_request())
    assert transport.calls == 1


def test_a_transient_failure_is_retried_by_the_same_gateway() -> None:
    transport = FakeTransport(500, {"error": {"message": "boom", "code": "internal"}})
    with pytest.raises(ModelGatewayError):
        _gateway(transport).complete(_request())
    assert transport.calls == 3  # initial attempt + the gateway's 2 retries


# ---------------------------------------------------------------------------
# attribution at the routing gateway
# ---------------------------------------------------------------------------


class _RaisingGateway:
    def __init__(self, error: ModelGatewayError) -> None:
        self.error = error

    def complete(self, request: ModelRequest) -> ModelResponse:
        raise self.error


class _OkGateway:
    def complete(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(
            content="ok",
            model=request.model or "m",
            usage=ModelUsage(prompt_tokens=1, completion_tokens=1),
            finish_reason="stop",
        )


def _settings(tmp_path: Path, **overrides: object) -> ModelSettings:
    settings = ModelSettings(tmp_path / "s.json")
    payload: dict[str, object] = {
        "provider": "custom",
        "model": "shared-model",
        "baseUrl": "https://example.test:8443/v1/models?key=hidden",
        "apiKey": "test-key-12345",
    }
    payload.update(overrides)
    settings.update(payload)
    return settings


def _routed_error(settings: ModelSettings, metadata: dict) -> ModelGatewayError:
    raw = ModelGatewayError(
        "LLM_MODEL_NOT_SUPPORTED",
        "Model provider error (HTTP 400): raw",
        details={"httpStatus": 400},
    )
    router = SettingsRoutingGateway(
        settings,
        _OkGateway(),
        gateway_factory=lambda s, t: _RaisingGateway(raw),
    )
    with pytest.raises(ModelGatewayError) as caught:
        router.complete(_request(metadata))
    return caught.value


def _serialized(error: ModelGatewayError) -> str:
    return json.dumps(error.to_platform_error(datetime.now(UTC))) + error.message


def test_attribution_for_a_per_agent_override(tmp_path: Path) -> None:
    settings = _settings(tmp_path, agentModels={"fix": "admin"})
    error = _routed_error(settings, {"agentId": "agent-fix"})
    assert error.code == "LLM_MODEL_NOT_SUPPORTED"
    assert error.retryable is False
    assert error.details["agent"] == "fix"
    assert error.details["model"] == "admin"
    assert error.details["source"] == "agentModels.fix"
    assert error.details["provider"] == "custom"
    assert error.details["baseUrlHost"] == "example.test"
    assert error.details["httpStatus"] == 400
    assert "Model 'admin'" in error.message
    assert "agentModels.fix" in error.message
    assert "Fix agent" in error.message
    assert "clear the override" in error.message
    blob = _serialized(error)
    assert "test-key-12345" not in blob  # the stored API key
    assert "hidden" not in blob  # the base URL's query
    assert "8443" not in blob  # the base URL's port
    assert "/v1" not in blob  # the base URL's path


def test_attribution_for_the_shared_model(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    error = _routed_error(settings, {"agentId": "agent-plan"})
    assert error.details["agent"] == "plan"
    assert error.details["model"] == "shared-model"
    assert error.details["source"] == "shared"
    assert "Settings > Model" in error.message


def test_attribution_for_the_complex_tier(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path,
        model="strong-model",
        agentModels={"fix": "cheap-model"},
    )
    error = _routed_error(settings, {"agentId": "agent-fix", "modelTier": "complex"})
    assert error.details["model"] == "strong-model"
    assert error.details["source"] == "complex-tier"
    assert settings.model_source("agent-fix", "complex") == "complex-tier"
    assert settings.model_source("agent-fix", None) == "agentModels.fix"
    assert settings.model_source("agent-plan", None) == "shared"


def test_base_url_credentials_never_reach_the_error(tmp_path: Path) -> None:
    settings = _settings(tmp_path, baseUrl="https://user:passw0rd@example.test/v1")
    error = _routed_error(settings, {"agentId": "agent-fix"})
    assert error.details["baseUrlHost"] == "example.test"
    blob = _serialized(error)
    assert "passw0rd" not in blob
    assert "user" not in error.details["baseUrlHost"]


def test_agent_key_maps_the_artifact_review_agent() -> None:
    assert agent_key("agent-artifact-review") == "artifact-review"
    assert agent_key("decomposer") is None


def test_attribution_for_the_artifact_review_agent(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    error = _routed_error(settings, {"agentId": "agent-artifact-review"})
    assert error.details["agent"] == "artifact-review"
    assert error.details["model"] == "shared-model"
    assert error.details["source"] == "shared"


def test_attribution_for_an_artifact_review_override(tmp_path: Path) -> None:
    settings = _settings(tmp_path, agentModels={"artifact-review": "reviewer-model"})
    error = _routed_error(settings, {"agentId": "agent-artifact-review"})
    assert error.details["agent"] == "artifact-review"
    assert error.details["model"] == "reviewer-model"
    assert error.details["source"] == "agentModels.artifact-review"
    assert "Artifact-review agent" in error.message
    assert "clear the override" in error.message


def test_attribution_for_an_unmapped_caller_names_the_stamped_id(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    error = _routed_error(settings, {"agentId": "decomposer", "modelTier": "complex"})
    assert error.details["agent"] == "decomposer"
    assert error.details["source"] == "complex-tier"


def test_attribution_without_any_agent_id_stays_unknown(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    error = _routed_error(settings, {})
    assert error.details["agent"] == "unknown"
    assert error.details["source"] == "shared"


def test_other_gateway_errors_pass_through_unenriched(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    raw = ModelGatewayError("LLM_BAD_REQUEST", "some other failure")
    router = SettingsRoutingGateway(
        settings,
        _OkGateway(),
        gateway_factory=lambda s, t: _RaisingGateway(raw),
    )
    with pytest.raises(ModelGatewayError) as caught:
        router.complete(_request({"agentId": "agent-fix"}))
    assert caught.value is raw
    assert "agent" not in caught.value.details


def test_routing_rewrite_keeps_the_provider_evidence(tmp_path: Path) -> None:
    """The friendly rewrite replaces the message; the provider's own
    code and message must survive in the details — they are the only
    place the actual diagnosis remains once the rewrite lands."""
    settings = _settings(tmp_path)
    raw = ModelGatewayError(
        "LLM_MODEL_NOT_SUPPORTED",
        "Model provider error (HTTP 400): The requested model is not supported.",
        details={
            "httpStatus": 400,
            "providerCode": "model_not_supported",
            "providerMessage": "The requested model is not supported.",
        },
    )
    router = SettingsRoutingGateway(
        settings,
        _OkGateway(),
        gateway_factory=lambda s, t: _RaisingGateway(raw),
    )
    with pytest.raises(ModelGatewayError) as caught:
        router.complete(_request({"agentId": "agent-fix"}))
    error = caught.value
    assert "is not supported by the provider" in error.message
    assert error.details["providerCode"] == "model_not_supported"
    assert error.details["providerMessage"] == "The requested model is not supported."
