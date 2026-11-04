"""UI-managed model provider settings (provider, model, API key).

Until now, switching the agents' model meant editing platform YAML,
setting environment variables, and using a custom assembly. This
module keeps a small settings record — provider, model, optional base
URL, and the API key — in a JSON file owned by the running backend, so
the dashboard Settings page can manage it directly:

- The API key is only ever written by the user and read by the gateway
  factory. API responses expose ``keyConfigured`` + a last-4 hint,
  never the key itself.
- The file lives next to the backend's data (the demo puts it beside
  the SQLite DB, overridable via ``ASF_MODEL_SETTINGS_FILE``). It is a
  local runtime file, not a project profile: it must never be committed
  or copied into a repository.

:class:`SettingsRoutingGateway` is the ModelGateway the agents see:
with the ``scripted`` provider it delegates to the assembly's fallback
gateway (the demo's canned replies); with a real provider configured
it builds that provider's gateway and pins every request to the
configured model. Settings changes take effect on the next agent call
— no restart.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable

from asf.contracts.models import ModelMessage, ModelRequest, ModelResponse
from asf.integrations.gemini import GeminiModelGateway
from asf.integrations.openai_compatible import HttpTransport, OpenAICompatibleGateway
from asf.models.errors import ModelGatewayError
from asf.models.ports import ModelGateway

__all__ = [
    "PROVIDERS",
    "ModelSettings",
    "SettingsRoutingGateway",
    "build_configured_gateway",
]

PROVIDERS = ("scripted", "gemini", "openai", "github-models", "meta", "custom")

DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "github-models": "https://models.github.ai/inference",
    "meta": "https://api.meta.ai/v1",
}

_DEFAULTS: dict[str, str] = {
    "provider": "scripted", "model": "", "baseUrl": "", "apiKey": "",
}


class ModelSettings:
    """The settings record, persisted to a JSON file when given a path."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._data: dict[str, str] = dict(_DEFAULTS)
        if path is not None and path.is_file():
            try:
                stored = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                stored = None
            if isinstance(stored, dict):
                for key in _DEFAULTS:
                    if isinstance(stored.get(key), str):
                        self._data[key] = stored[key]
                if self._data["provider"] not in PROVIDERS:
                    self._data["provider"] = "scripted"

    # -- reads ---------------------------------------------------------------
    def current(self) -> dict[str, str]:
        return dict(self._data)

    def public(self) -> dict[str, Any]:
        key = self._data["apiKey"]
        return {
            "provider": self._data["provider"],
            "model": self._data["model"],
            "baseUrl": self._data["baseUrl"],
            "keyConfigured": bool(key),
            "keyHint": f"…{key[-4:]}" if len(key) >= 4 else "",
        }

    # -- writes --------------------------------------------------------------
    def update(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        data = dict(self._data)
        provider = payload.get("provider", data["provider"])
        if provider not in PROVIDERS:
            raise ValueError(
                f"Unknown model provider {provider!r}; "
                f"expected one of {', '.join(PROVIDERS)}",
            )
        data["provider"] = str(provider)
        for field in ("model", "baseUrl"):
            if field in payload:
                value = payload[field]
                if not isinstance(value, str):
                    raise ValueError(f"{field} must be a string")
                data[field] = value.strip()
        if payload.get("clearKey") is True:
            data["apiKey"] = ""
        api_key = payload.get("apiKey")
        if isinstance(api_key, str) and api_key:
            data["apiKey"] = api_key
        if data["provider"] != "scripted" and not data["model"]:
            raise ValueError(
                f"A model name is required for provider '{data['provider']}'",
            )
        if data["provider"] == "custom" and not data["baseUrl"].startswith(
            ("https://", "http://"),
        ):
            raise ValueError(
                "The custom provider needs a base URL (http/https)",
            )
        self._data = data
        self._persist()
        return self.public()

    def test(self, transport: HttpTransport | None = None) -> dict[str, Any]:
        """One tiny completion through the configured provider."""
        settings = self.current()
        if settings["provider"] == "scripted":
            return {
                "ok": True,
                "message": "Scripted demo provider: agents use canned "
                           "replies, no network call to test.",
            }
        try:
            gateway = build_configured_gateway(settings, transport)
        except (ValueError, ModelGatewayError) as error:
            return {"ok": False, "message": str(error)}
        if gateway is None:
            return {"ok": False, "message": "No provider configured."}
        try:
            response = gateway.complete(ModelRequest(
                messages=[ModelMessage(
                    role="user", content="Reply with the single word OK",
                )],
                model=settings["model"] or None,
            ))
        except ModelGatewayError as error:
            return {"ok": False, "message": error.message}
        except Exception as error:  # transport-level surprises
            return {"ok": False, "message": f"{type(error).__name__}: {error}"}
        if response.content.strip():
            return {
                "ok": True,
                "message": f"Provider answered with model "
                           f"'{response.model}': {response.content.strip()[:80]!r}",
            }
        return {"ok": False, "message": "Provider answered with empty content."}

    def _persist(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._data, indent=2), encoding="utf-8",
        )


def build_configured_gateway(
    settings: Mapping[str, str], transport: HttpTransport | None = None,
) -> ModelGateway | None:
    """The real provider gateway for the settings, or None for scripted."""
    provider = settings.get("provider", "scripted")
    if provider == "scripted":
        return None
    model = (settings.get("model") or "").strip()
    api_key = settings.get("apiKey") or ""
    if not api_key:
        raise ValueError(
            f"No API key stored for provider '{provider}'. "
            "Save a key in Settings first.",
        )
    if provider == "gemini":
        return GeminiModelGateway(model=model, api_key=api_key)
    base_url = (settings.get("baseUrl") or "").strip() or DEFAULT_BASE_URLS.get(
        provider, "",
    )
    return OpenAICompatibleGateway(
        base_url=base_url, model=model, api_key=api_key, transport=transport,
    )


class SettingsRoutingGateway:
    """ModelGateway that follows the current settings on every call."""

    def __init__(
        self,
        settings: ModelSettings,
        fallback: ModelGateway,
        transport: HttpTransport | None = None,
        gateway_factory: Callable[
            [Mapping[str, str], HttpTransport | None], ModelGateway | None,
        ] = build_configured_gateway,
    ) -> None:
        self._settings = settings
        self._fallback = fallback
        self._transport = transport
        self._factory = gateway_factory
        self._cached_for: dict[str, str] | None = None
        self._cached: ModelGateway | None = None

    def complete(self, request: ModelRequest) -> ModelResponse:
        current = self._settings.current()
        gateway = self._resolve(current)
        if gateway is None:
            return self._fallback.complete(request)
        model = current.get("model", "").strip()
        if model:
            request = request.model_copy(update={"model": model})
        return gateway.complete(request)

    def _resolve(self, current: dict[str, str]) -> ModelGateway | None:
        if self._cached_for is not None and self._cached_for == current:
            return self._cached
        try:
            gateway = self._factory(current, self._transport)
        except (ValueError, ModelGatewayError) as error:
            raise ModelGatewayError(
                "INTEGRATION_UNAVAILABLE",
                f"Configured model provider is unusable: {error}",
            ) from None
        self._cached_for = dict(current)
        self._cached = gateway
        return gateway
