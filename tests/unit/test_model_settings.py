"""Model provider settings: store, gateway factory, routing gateway."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from asf.api.model_settings import (
    ModelSettings,
    SettingsRoutingGateway,
    build_configured_gateway,
)
from asf.contracts.models import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelUsage,
)
from asf.integrations.openai_compatible import OpenAICompatibleGateway


def _request(model: str | None = None) -> ModelRequest:
    return ModelRequest(
        messages=[ModelMessage(role="user", content="hi")], model=model,
    )


def _response(content: str, model: str = "m") -> ModelResponse:
    return ModelResponse(
        content=content, model=model,
        usage=ModelUsage(prompt_tokens=1, completion_tokens=1),
        finish_reason="stop",
    )


class RecordingGateway:
    def __init__(self, content: str = "real") -> None:
        self.content = content
        self.requests: list[ModelRequest] = []

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return _response(self.content, request.model or "m")


# ---------------------------------------------------------------------------
# store
# ---------------------------------------------------------------------------

def test_defaults_and_public_view_hide_the_key(tmp_path: Path):
    settings = ModelSettings(tmp_path / "model-settings.json")
    assert settings.public() == {
        "provider": "scripted", "model": "", "baseUrl": "",
        "agentModels": {}, "keyConfigured": False, "keyHint": "",
    }
    view = settings.update({
        "provider": "gemini", "model": "gemini-x", "apiKey": "AIza-secret-1234",
    })
    assert view["keyConfigured"] is True
    assert view["keyHint"] == "…1234"
    assert "apiKey" not in view
    assert "AIza" not in json.dumps(view)


def test_key_keep_replace_clear_and_persistence(tmp_path: Path):
    path = tmp_path / "model-settings.json"
    settings = ModelSettings(path)
    settings.update({"provider": "openai", "model": "gpt-x", "apiKey": "sk-1111"})
    # Absent apiKey keeps the stored one.
    settings.update({"provider": "openai", "model": "gpt-y"})
    assert settings.current()["apiKey"] == "sk-1111"
    # A new key replaces it.
    settings.update({"provider": "openai", "model": "gpt-y", "apiKey": "sk-2222"})
    assert settings.current()["apiKey"] == "sk-2222"
    # Reloaded from disk.
    assert ModelSettings(path).current()["apiKey"] == "sk-2222"
    # clearKey removes it.
    settings.update({"provider": "openai", "model": "gpt-y", "clearKey": True})
    assert settings.current()["apiKey"] == ""
    assert settings.public()["keyConfigured"] is False


def test_update_validation(tmp_path: Path):
    settings = ModelSettings(tmp_path / "s.json")
    with pytest.raises(ValueError, match="Unknown model provider"):
        settings.update({"provider": "wat"})
    with pytest.raises(ValueError, match="model name is required"):
        settings.update({"provider": "gemini", "model": ""})
    with pytest.raises(ValueError, match="base URL"):
        settings.update({"provider": "custom", "model": "m", "baseUrl": ""})
    updated = settings.update({
        "provider": "custom", "model": "m", "baseUrl": "https://x/v1",
    })
    assert updated["provider"] == "custom"


# ---------------------------------------------------------------------------
# factory + connection test
# ---------------------------------------------------------------------------

def test_factory_scripted_none_and_missing_key():
    assert build_configured_gateway({"provider": "scripted"}) is None
    with pytest.raises(ValueError, match="No API key stored"):
        build_configured_gateway({"provider": "openai", "model": "gpt-x"})


def test_factory_builds_openai_compatible_with_default_base():
    gateway = build_configured_gateway({
        "provider": "github-models", "model": "openai/gpt-4o",
        "apiKey": "ghp_x", "baseUrl": "",
    })
    assert isinstance(gateway, OpenAICompatibleGateway)


class _RecordingTransport:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def post(self, url, *, headers, body, timeout_seconds):  # noqa: ANN001, ANN202
        self.urls.append(url)
        payload = {
            "model": "muse-spark-1.3",
            "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }
        return 200, json.dumps(payload).encode()


def test_factory_meta_preset_targets_meta_model_api():
    transport = _RecordingTransport()
    gateway = build_configured_gateway({
        "provider": "meta", "model": "muse-spark-1.3",
        "apiKey": "meta-key", "baseUrl": "",
    }, transport)
    assert isinstance(gateway, OpenAICompatibleGateway)
    response = gateway.complete(_request())
    assert response.content == "hi"
    assert transport.urls == ["https://api.meta.ai/v1/chat/completions"]


class _OkTransport:
    def post(self, url, *, headers, body, timeout_seconds):  # noqa: ANN001, ANN202
        payload = {
            "model": "gpt-x",
            "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 1},
        }
        return 200, json.dumps(payload).encode()


def test_connection_test_paths(tmp_path: Path):
    settings = ModelSettings(tmp_path / "s.json")
    scripted = settings.test()
    assert scripted["ok"] is True

    settings.update({"provider": "openai", "model": "gpt-x"})
    missing = settings.test()
    assert missing["ok"] is False
    assert "No API key stored" in missing["message"]

    settings.update({"provider": "openai", "model": "gpt-x", "apiKey": "sk-1"})
    ok = settings.test(_OkTransport())
    assert ok["ok"] is True
    assert "gpt-x" in ok["message"]


# ---------------------------------------------------------------------------
# routing gateway
# ---------------------------------------------------------------------------

def test_router_falls_back_when_scripted(tmp_path: Path):
    settings = ModelSettings(tmp_path / "s.json")
    fallback = RecordingGateway("scripted")
    router = SettingsRoutingGateway(settings, fallback)
    assert router.complete(_request()).content == "scripted"


def test_router_delegates_and_pins_the_configured_model(tmp_path: Path):
    settings = ModelSettings(tmp_path / "s.json")
    settings.update({
        "provider": "openai", "model": "gpt-real", "apiKey": "sk-1",
    })
    real = RecordingGateway("real-answer")
    router = SettingsRoutingGateway(
        settings, RecordingGateway("scripted"),
        gateway_factory=lambda s, t: real,
    )
    response = router.complete(_request(model="agent-pinned"))
    assert response.content == "real-answer"
    assert real.requests[0].model == "gpt-real"  # settings model wins


# ---------------------------------------------------------------------------
# per-agent model overrides
# ---------------------------------------------------------------------------

def test_per_agent_overrides_store_validate_and_persist(tmp_path: Path):
    path = tmp_path / "s.json"
    settings = ModelSettings(path)
    view = settings.update({
        "provider": "custom", "model": "shared-m",
        "baseUrl": "https://x/v1", "apiKey": "k-1",
        "agentModels": {
            "implement": " code-m ", "agent-spec": "spec-m", "fix": "",
        },
    })
    # Values are trimmed, blanks drop out, agent- ids normalize.
    assert view["agentModels"] == {"implement": "code-m", "spec": "spec-m"}
    assert settings.effective_model("implement") == "code-m"
    assert settings.effective_model("agent-spec") == "spec-m"
    assert settings.effective_model("plan") == "shared-m"
    assert settings.effective_model(None) == "shared-m"
    # Persisted beside the other settings and reloaded.
    assert ModelSettings(path).agent_models() == {
        "implement": "code-m", "spec": "spec-m",
    }
    # A later update replaces the whole map (the dashboard sends it all).
    settings.update({
        "provider": "custom", "model": "shared-m",
        "baseUrl": "https://x/v1", "agentModels": {"review": "rev-m"},
    })
    assert settings.agent_models() == {"review": "rev-m"}
    # The Test agent has no model to override; unknown agents are errors.
    with pytest.raises(ValueError, match="Unknown agent"):
        settings.update({"agentModels": {"test": "m"}})
    with pytest.raises(ValueError, match="Unknown agent"):
        settings.update({"agentModels": {"nope": "m"}})
    with pytest.raises(ValueError, match="must be an object"):
        settings.update({"agentModels": "implement=m"})


def test_router_pins_per_agent_models(tmp_path: Path):
    settings = ModelSettings(tmp_path / "s.json")
    settings.update({
        "provider": "openai", "model": "gpt-shared", "apiKey": "sk-1",
        "agentModels": {"implement": "gpt-code", "review": "gpt-review"},
    })
    real = RecordingGateway("real-answer")
    router = SettingsRoutingGateway(
        settings, RecordingGateway("scripted"),
        gateway_factory=lambda s, t: real,
    )

    def call(agent_id: str | None) -> str | None:
        metadata = {"agentId": agent_id} if agent_id else {}
        return router.complete(ModelRequest(
            messages=[ModelMessage(role="user", content="hi")],
            metadata=metadata,
        )).model

    assert call("agent-implement") == "gpt-code"
    assert call("agent-review") == "gpt-review"
    assert call("agent-spec") == "gpt-shared"   # no override -> shared
    assert call(None) == "gpt-shared"           # unattributed -> shared
    assert call("agent-test") == "gpt-shared"   # test never overrides


def test_complex_tier_upgrades_every_agent_to_the_shared_model(tmp_path: Path):
    settings = ModelSettings(tmp_path / "s.json")
    settings.update({
        "provider": "openai", "model": "gpt-shared", "apiKey": "sk-1",
        "agentModels": {"implement": "gpt-code", "spec": "gpt-cheap"},
    })
    # Resolution: complex ignores the economy overrides, standard keeps them.
    assert settings.effective_model("implement", "complex") == "gpt-shared"
    assert settings.effective_model("spec", "complex") == "gpt-shared"
    assert settings.effective_model("implement") == "gpt-code"
    assert settings.effective_model("implement", "standard") == "gpt-code"

    real = RecordingGateway("real-answer")
    router = SettingsRoutingGateway(
        settings, RecordingGateway("scripted"),
        gateway_factory=lambda s, t: real,
    )

    def call(metadata: dict) -> str | None:
        return router.complete(ModelRequest(
            messages=[ModelMessage(role="user", content="hi")],
            metadata=metadata,
        )).model

    assert call({"agentId": "agent-implement", "modelTier": "complex"}) == "gpt-shared"
    assert call({"agentId": "agent-implement"}) == "gpt-code"
    assert call({"agentId": "agent-spec", "modelTier": "complex"}) == "gpt-shared"


class _RecordingTransport:
    def __init__(self) -> None:
        self.models: list[str] = []

    def post(self, url, *, headers, body, timeout_seconds):  # noqa: ANN001, ANN202
        self.models.append(json.loads(body)["model"])
        payload = {
            "model": "whatever",
            "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 1},
        }
        return 200, json.dumps(payload).encode()


def test_connection_test_uses_the_agents_effective_model(tmp_path: Path):
    settings = ModelSettings(tmp_path / "s.json")
    settings.update({
        "provider": "openai", "model": "gpt-shared", "apiKey": "sk-1",
        "agentModels": {"fix": "gpt-fix"},
    })
    transport = _RecordingTransport()
    assert settings.test(transport)["ok"] is True
    assert settings.test(transport, agent="fix")["ok"] is True
    assert settings.test(transport, agent="spec")["ok"] is True
    assert transport.models == ["gpt-shared", "gpt-fix", "gpt-shared"]
    unknown = settings.test(transport, agent="test")
    assert unknown["ok"] is False
    assert "Unknown agent" in unknown["message"]
