"""Per-agent connection profiles: routing, fallback, masking, rules."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from asf.api.model_settings import (
    ModelSettings,
    SettingsRoutingGateway,
    build_configured_gateway,
)
from asf.contracts.models import ModelMessage, ModelRequest, ModelResponse, ModelUsage
from asf.integrations.header_transport import HeaderInjectingTransport
from asf.models.errors import ModelGatewayError

SHARED = {
    "provider": "custom",
    "model": "shared-m",
    "baseUrl": "https://shared.example/v1",
    "apiKey": "shared-key-0001",
}


def _settings(tmp_path: Path) -> ModelSettings:
    settings = ModelSettings(tmp_path / "model-settings.json")
    settings.update(dict(SHARED))
    return settings


def _request(agent: str | None = None) -> ModelRequest:
    metadata = {"agentId": f"agent-{agent}"} if agent else {}
    return ModelRequest(
        messages=[ModelMessage(role="user", content="hi")],
        metadata=metadata,
    )


def _response(content: str) -> ModelResponse:
    return ModelResponse(
        content=content,
        model="m",
        usage=ModelUsage(prompt_tokens=1, completion_tokens=1),
        finish_reason="stop",
    )


class _EchoGateway:
    """Stands in for a provider gateway; answers with its own base URL."""

    def __init__(self, settings: dict[str, Any]) -> None:
        self.settings = settings

    def complete(self, request: ModelRequest) -> ModelResponse:
        return _response(str(self.settings.get("baseUrl")))


def _router(settings: ModelSettings) -> SettingsRoutingGateway:
    return SettingsRoutingGateway(
        settings,
        _EchoGateway({}),
        gateway_factory=lambda s, t: _EchoGateway(dict(s)),
    )


def test_each_agent_calls_its_own_endpoint(tmp_path: Path):
    settings = _settings(tmp_path)
    settings.update(
        {
            "agentConnections": {
                "spec": {"baseUrl": "https://spec.example/v1", "apiKey": "spec-key-1111"},
                "review": {"baseUrl": "http://127.0.0.1:18610/v1", "apiKey": "review-key-2222"},
            }
        }
    )
    router = _router(settings)
    assert router.complete(_request("spec")).content == "https://spec.example/v1"
    assert router.complete(_request("review")).content == "http://127.0.0.1:18610/v1"


def test_agent_without_a_profile_uses_the_shared_endpoint(tmp_path: Path):
    settings = _settings(tmp_path)
    settings.update({"agentConnections": {"spec": {"baseUrl": "https://spec.example/v1"}}})
    router = _router(settings)
    assert router.complete(_request("plan")).content == "https://shared.example/v1"
    assert router.complete(_request()).content == "https://shared.example/v1"


def test_editing_one_profile_leaves_the_others_alone(tmp_path: Path):
    settings = _settings(tmp_path)
    settings.update(
        {
            "agentConnections": {
                "spec": {"baseUrl": "https://a.example/v1"},
                "review": {"baseUrl": "https://b.example/v1"},
            }
        }
    )
    settings.update({"agentConnections": {"spec": {"baseUrl": "https://a2.example/v1"}}})
    effective = settings.effective_settings("review")
    assert effective["baseUrl"] == "https://b.example/v1"
    assert settings.effective_settings("spec")["baseUrl"] == "https://a2.example/v1"


def test_profiles_persist_and_old_files_load_without_them(tmp_path: Path):
    path = tmp_path / "model-settings.json"
    settings = ModelSettings(path)
    settings.update(dict(SHARED))
    settings.update(
        {"agentConnections": {"fix": {"timeoutSeconds": 45, "headers": {"X-Tenant": "t1"}}}}
    )
    reloaded = ModelSettings(path)
    profile = reloaded.agent_connections()["fix"]
    assert profile["timeoutSeconds"] == 45
    assert profile["headers"] == {"X-Tenant": "t1"}
    legacy = tmp_path / "legacy.json"
    legacy.write_text(json.dumps(dict(SHARED)), encoding="utf-8")
    assert ModelSettings(legacy).agent_connections() == {}


def test_public_view_masks_keys_and_header_values(tmp_path: Path):
    settings = _settings(tmp_path)
    settings.update(
        {
            "agentConnections": {
                "spec": {
                    "baseUrl": "http://127.0.0.1:9000/v1",
                    "apiKey": "spec-secret-9999",
                    "headers": {"X-Proxy-Token": "header-secret-8888"},
                }
            }
        }
    )
    view = settings.public()
    blob = json.dumps(view)
    assert "spec-secret-9999" not in blob
    assert "header-secret-8888" not in blob
    profile = view["agentConnections"]["spec"]
    assert profile["keyConfigured"] is True
    assert profile["keyHint"] == "…9999"
    assert profile["headers"] == {"X-Proxy-Token": "****"}
    assert profile["insecureHttp"] is True


def test_key_is_write_only_and_an_empty_profile_removes_it(tmp_path: Path):
    settings = _settings(tmp_path)
    settings.update(
        {"agentConnections": {"spec": {"apiKey": "keep-me-1234", "timeoutSeconds": 30}}}
    )
    settings.update({"agentConnections": {"spec": {"timeoutSeconds": 60}}})
    assert settings.agent_connections()["spec"]["apiKey"] == "keep-me-1234"
    settings.update({"agentConnections": {"spec": {"clearKey": True}}})
    assert settings.agent_connections()["spec"]["apiKey"] == ""
    settings.update({"agentConnections": {"spec": {}}})
    assert "spec" not in settings.agent_connections()


@pytest.mark.parametrize(
    "profile",
    [
        {"baseUrl": "https://169.254.169.254/latest/meta-data"},
        {"baseUrl": "ftp://example.com/v1"},
        {"baseUrl": "https://"},
        {"baseUrl": "not a url"},
        {"provider": "carrier-pigeon"},
        {"headers": {"Authorization": "Bearer x"}},
        {"headers": {"Content-Type": "text/plain"}},
        {"headers": {"Bad Name": "x"}},
        {"headers": {"X-Ok": "a\r\nInjected: 1"}},
        {"timeoutSeconds": 0},
        {"timeoutSeconds": 3601},
        {"timeoutSeconds": "30"},
        {"surprise": True},
    ],
)
def test_invalid_profiles_are_rejected(tmp_path: Path, profile: dict[str, Any]):
    settings = _settings(tmp_path)
    with pytest.raises(ValueError):
        settings.update({"agentConnections": {"spec": profile}})


def test_local_and_private_urls_are_allowed(tmp_path: Path):
    settings = _settings(tmp_path)
    settings.update(
        {
            "agentConnections": {
                "spec": {"baseUrl": "http://localhost:4141/v1"},
                "plan": {"baseUrl": "http://192.168.1.20:8080/v1"},
            }
        }
    )
    assert settings.effective_settings("spec")["baseUrl"] == "http://localhost:4141/v1"
    assert settings.effective_settings("plan")["baseUrl"] == "http://192.168.1.20:8080/v1"


def test_unknown_agent_and_custom_without_url_are_rejected(tmp_path: Path):
    settings = _settings(tmp_path)
    with pytest.raises(ValueError):
        settings.update({"agentConnections": {"test": {"timeoutSeconds": 5}}})
    bare = ModelSettings(tmp_path / "bare.json")
    bare.update({"provider": "openai", "model": "m", "apiKey": "k"})
    with pytest.raises(ValueError):
        bare.update({"agentConnections": {"spec": {"provider": "custom"}}})


class _RecordingTransport:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, **kwargs: Any) -> tuple[int, dict[str, str], bytes]:
        self.calls.append({"url": url, **kwargs})
        body = json.dumps({"choices": [{"message": {"content": "OK"}}], "usage": {}}).encode()
        return 200, {}, body


def test_factory_merges_profile_headers_and_timeout(tmp_path: Path):
    settings = _settings(tmp_path)
    settings.update(
        {
            "agentConnections": {
                "spec": {
                    "baseUrl": "https://spec.example/v1",
                    "apiKey": "spec-key-1111",
                    "headers": {"X-Client": "asf-spec"},
                    "timeoutSeconds": 12,
                }
            }
        }
    )
    transport = _RecordingTransport()
    gateway = build_configured_gateway(settings.effective_settings("spec"), transport)
    assert gateway is not None
    gateway.complete(_request("spec"))
    call = transport.calls[0]
    assert call["url"] == "https://spec.example/v1/chat/completions"
    assert call["headers"]["X-Client"] == "asf-spec"
    assert call["headers"]["Authorization"] == "Bearer spec-key-1111"
    assert call["timeout_seconds"] == 12.0


def test_test_connection_uses_the_agents_own_profile(tmp_path: Path):
    settings = _settings(tmp_path)
    settings.update(
        {
            "agentConnections": {
                "review": {"baseUrl": "https://review.example/v1", "apiKey": "review-key-2222"}
            }
        }
    )
    transport = _RecordingTransport()
    result = settings.test(transport, agent="review")
    assert result["ok"] is True
    call = transport.calls[0]
    assert call["url"].startswith("https://review.example/v1")
    assert call["headers"]["Authorization"] == "Bearer review-key-2222"


class _FailingGateway:
    def complete(self, request: ModelRequest) -> ModelResponse:
        raise ModelGatewayError("LLM_TIMEOUT", "timed out")


def test_failure_log_names_agent_and_host_never_secrets(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    settings = _settings(tmp_path)
    settings.update(
        {
            "agentConnections": {
                "spec": {
                    "baseUrl": "https://spec.example/v1",
                    "apiKey": "spec-secret-9999",
                    "headers": {"X-Proxy-Token": "header-secret-8888"},
                }
            }
        }
    )
    router = SettingsRoutingGateway(
        settings,
        _EchoGateway({}),
        gateway_factory=lambda s, t: _FailingGateway(),
    )
    with (
        caplog.at_level(logging.WARNING, logger="asf.api.model_settings"),
        pytest.raises(ModelGatewayError),
    ):
        router.complete(_request("spec"))
    text = caplog.text
    assert "agent-spec" in text
    assert "spec.example" in text
    assert "spec-secret-9999" not in text
    assert "header-secret-8888" not in text


def test_header_transport_merges_and_forwards_kwargs():
    seen: dict[str, Any] = {}

    class _Inner:
        def post(self, url: str, **kwargs: Any) -> str:
            seen.update(kwargs)
            return "done"

    transport = HeaderInjectingTransport(
        _Inner(), {"X-Extra": "1", "Authorization": "Bearer extra"}
    )
    result = transport.post(
        "https://x.example",
        headers={"Authorization": "Bearer real", "Content-Type": "application/json"},
        body=b"{}",
        timeout_seconds=3.0,
        max_response_bytes=99,
    )
    assert result == "done"
    assert seen["headers"]["X-Extra"] == "1"
    assert seen["headers"]["Authorization"] == "Bearer real"
    assert seen["max_response_bytes"] == 99
