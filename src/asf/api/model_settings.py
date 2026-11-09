"""UI-managed model provider settings (provider, model, API key).

Until now, switching the agents' model meant editing platform YAML,
setting environment variables, and using a custom assembly. This
module keeps a small settings record — provider, model, optional base
URL, and the API key — in a JSON file owned by the running backend, so
the dashboard Settings page can manage it directly:

- The API key is only ever written by the user and read by the gateway
  factory. API responses expose ``keyConfigured`` + a last-4 hint,
  never the key itself.
- The file lives in the backend's data directory (the demo anchors
  it there; overridable via ``ASF_MODEL_SETTINGS_FILE``). It is a
  local runtime file, not a project profile: it must never be committed
  or copied into a repository.

:class:`SettingsRoutingGateway` is the ModelGateway the agents see:
with the ``scripted`` provider it delegates to the assembly's fallback
gateway (the demo's canned replies); with a real provider configured
it builds that provider's gateway and pins every request to the
configured model. Settings changes take effect on the next agent call
— no restart.

On top of the one shared model, the record carries optional
**per-agent model overrides** (``agentModels``): each AI agent may name
its own model on the same provider/endpoint/key, and an agent without
an override uses the shared model. The routing gateway picks the model
per call from the calling agent's ``agentId`` request metadata. The
Test agent never calls a model, so it has no override.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from asf.api.model_ids import checked_model_id, normalize_stored_model_id
from asf.contracts.models import ModelMessage, ModelRequest, ModelResponse
from asf.integrations.gemini import GeminiModelGateway
from asf.integrations.openai_compatible import HttpTransport, OpenAICompatibleGateway
from asf.models.errors import ModelGatewayError
from asf.models.ports import ModelGateway

logger = logging.getLogger(__name__)

__all__ = [
    "MODEL_AGENTS",
    "PROVIDERS",
    "ModelSettings",
    "SettingsRoutingGateway",
    "build_configured_gateway",
]

PROVIDERS = ("scripted", "gemini", "openai", "github-models", "meta", "custom")

#: Agents that call a model and may carry a per-agent model override,
#: keyed by agent type. The Test agent is deterministic (no model
#: calls), so it is deliberately absent.
MODEL_AGENTS = ("spec", "plan", "task", "implement", "review", "fix")


def agent_key(raw: Any) -> str | None:
    """Normalize a request-metadata agent id to a MODEL_AGENTS key.

    Agents stamp their full metadata id (``agent-spec``); settings are
    keyed by the short type (``spec``). Anything unrecognized yields
    None, i.e. "use the shared model".
    """
    if not isinstance(raw, str):
        return None
    key = raw.strip()
    if key.startswith("agent-"):
        key = key[len("agent-") :]
    return key if key in MODEL_AGENTS else None


def _load_agent_models(raw: Any) -> dict[str, str]:
    """Stored per-agent models, normalised on load; never raises.

    Entries with an unknown agent or a non-string value are skipped
    (one corrupt entry cannot brick the settings); each kept id goes
    through the stored-id normalisation, which logs a WARNING when
    it changes or cannot fix the value.
    """
    if not isinstance(raw, Mapping):
        return {}
    cleaned: dict[str, str] = {}
    for key, value in raw.items():
        name = agent_key(key)
        if name is None or not isinstance(value, str):
            continue
        model = normalize_stored_model_id(f"agentModels.{name}", value)
        if model:
            cleaned[name] = model
    return cleaned


def _clean_field_value(field: str, value: str) -> str:
    """The stored form of a settings text field (model ids are checked)."""
    if field == "model":
        return checked_model_id("model", value)
    return value.strip()


DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "github-models": "https://models.github.ai/inference",
    "meta": "https://api.meta.ai/v1",
}

_DEFAULTS: dict[str, str] = {
    "provider": "scripted",
    "model": "",
    "baseUrl": "",
    "apiKey": "",
}


class ModelSettings:
    """The settings record, persisted to a JSON file when given a path."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._data: dict[str, str] = dict(_DEFAULTS)
        self._agent_models: dict[str, str] = {}
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
                self._data["model"] = normalize_stored_model_id(
                    "model",
                    self._data["model"],
                )
                self._agent_models = _load_agent_models(stored.get("agentModels"))

    @staticmethod
    def _clean_agent_models(raw: Any, *, strict: bool) -> dict[str, str]:
        """Validate/normalize an agentModels mapping.

        Keys are agent types (``agent-spec`` ids are normalized too);
        blank values mean "no override" and drop out. In strict mode
        (user input via the API) a malformed mapping or an unknown
        agent raises ValueError; when loading from disk, bad entries
        are skipped so one corrupt entry cannot brick the settings.
        """
        if raw is None:
            return {}
        if not isinstance(raw, Mapping):
            if strict:
                raise ValueError("agentModels must be an object keyed by agent")
            return {}
        cleaned: dict[str, str] = {}
        for key, value in raw.items():
            name = agent_key(key)
            if name is None or not isinstance(value, str):
                if strict:
                    raise ValueError(
                        f"Unknown agent {key!r} in agentModels; "
                        f"expected one of {', '.join(MODEL_AGENTS)}",
                    )
                continue
            model = checked_model_id(f"agentModels.{name}", value) if strict else value.strip()
            if model:
                cleaned[name] = model
        return cleaned

    # -- reads ---------------------------------------------------------------
    def current(self) -> dict[str, str]:
        return dict(self._data)

    def agent_models(self) -> dict[str, str]:
        """Per-agent model overrides (agent type -> model); may be empty."""
        return dict(self._agent_models)

    def effective_model(
        self,
        agent: str | None = None,
        tier: str | None = None,
    ) -> str:
        """The model a call from `agent` will use.

        Standard runs: the agent's override, else the shared model.
        A ``complex`` run (oversized requirement, classified at run
        start) upgrades every agent to the shared model — the
        strongest the user configured — because the economy per-agent
        models are the ones that truncate or lose the format on long
        work. When no shared model is set, the override still applies.
        """
        if tier == "complex" and self._data["model"].strip():
            return self._data["model"]
        key = agent_key(agent)
        if key is not None and key in self._agent_models:
            return self._agent_models[key]
        return self._data["model"]

    def model_source(
        self,
        agent: str | None = None,
        tier: str | None = None,
    ) -> str:
        """Where `effective_model`'s answer comes from, same inputs.

        One of "complex-tier" (a complex run on the shared model),
        "agentModels.<agent>" (the agent's own override) or "shared"
        (the shared model). Mirrors effective_model branch for
        branch; it exists so an unsupported-model failure can name
        the setting the operator has to fix.
        """
        if tier == "complex" and self._data["model"].strip():
            return "complex-tier"
        key = agent_key(agent)
        if key is not None and key in self._agent_models:
            return f"agentModels.{key}"
        return "shared"

    def public(self) -> dict[str, Any]:
        key = self._data["apiKey"]
        return {
            "provider": self._data["provider"],
            "model": self._data["model"],
            "baseUrl": self._data["baseUrl"],
            "agentModels": dict(self._agent_models),
            "keyConfigured": bool(key),
            "keyHint": f"…{key[-4:]}" if len(key) >= 4 else "",
        }

    # -- writes --------------------------------------------------------------
    def update(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        data = dict(self._data)
        provider = payload.get("provider", data["provider"])
        if provider not in PROVIDERS:
            raise ValueError(
                f"Unknown model provider {provider!r}; expected one of {', '.join(PROVIDERS)}",
            )
        data["provider"] = str(provider)
        for field in ("model", "baseUrl"):
            if field in payload:
                value = payload[field]
                if not isinstance(value, str):
                    raise ValueError(f"{field} must be a string")
                data[field] = _clean_field_value(field, value)
        agent_models = self._agent_models
        if "agentModels" in payload:
            agent_models = self._clean_agent_models(
                payload["agentModels"],
                strict=True,
            )
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
        self._agent_models = agent_models
        self._persist()
        return self.public()

    def test(
        self,
        transport: HttpTransport | None = None,
        agent: str | None = None,
    ) -> dict[str, Any]:
        """One tiny completion through the configured provider.

        With `agent`, the completion uses that agent's effective model
        (its override, else the shared model) so a per-agent choice can
        be verified on its own.
        """
        settings = self.current()
        agent_name = agent_key(agent) if agent is not None else None
        if agent is not None and agent_name is None:
            return {
                "ok": False,
                "message": f"Unknown agent {agent!r}; expected one of {', '.join(MODEL_AGENTS)}",
            }
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
            response = gateway.complete(
                ModelRequest(
                    messages=[
                        ModelMessage(
                            role="user",
                            content="Reply with the single word OK",
                        )
                    ],
                    model=self.effective_model(agent_name) or None,
                )
            )
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
        record: dict[str, Any] = dict(self._data)
        record["agentModels"] = dict(self._agent_models)
        self._path.write_text(
            json.dumps(record, indent=2),
            encoding="utf-8",
        )


def build_configured_gateway(
    settings: Mapping[str, str],
    transport: HttpTransport | None = None,
) -> ModelGateway | None:
    """The real provider gateway for the settings, or None for scripted."""
    provider = settings.get("provider", "scripted")
    if provider == "scripted":
        return None
    model = (settings.get("model") or "").strip()
    api_key = settings.get("apiKey") or ""
    if not api_key:
        raise ValueError(
            f"No API key stored for provider '{provider}'. Save a key in Settings first.",
        )
    if provider == "gemini":
        return GeminiModelGateway(model=model, api_key=api_key)
    base_url = (settings.get("baseUrl") or "").strip() or DEFAULT_BASE_URLS.get(
        provider,
        "",
    )
    return OpenAICompatibleGateway(
        base_url=base_url,
        model=model,
        api_key=api_key,
        transport=transport,
        # Anthropic's OpenAI-compatible endpoint understands
        # cache_control content parts; enable the agents' cache
        # prefix hint only there.
        prompt_cache="anthropic" in base_url,
    )


def _base_url_host(settings: ModelSettings) -> str:
    """The configured endpoint's hostname only, for error details.

    Never the credentials, port, path or query of the URL: an error
    detail is shown on dashboards and stored on runs, so it carries
    just enough to recognise which endpoint rejected the model.
    """
    current = settings.current()
    base = current["baseUrl"].strip() or DEFAULT_BASE_URLS.get(current["provider"], "")
    try:
        return urlsplit(base).hostname or ""
    except ValueError:
        return ""


def _unsupported_model_message(model: str, source: str, key: str | None) -> str:
    """The operator-facing sentence for an unsupported-model failure."""
    if source == "complex-tier":
        advice = (
            "this run is classified complex, so the shared model is used; "
            "fix it in Settings > Model"
        )
    elif source.startswith("agentModels."):
        advice = (
            f"fix it in Settings > Model > {(key or '').capitalize()} agent or clear the override"
        )
    else:
        advice = "fix it in Settings > Model"
    return f"Model '{model}' (source: {source}) is not supported by the provider; {advice}."


def _unsupported_model_error(
    error: ModelGatewayError,
    settings: ModelSettings,
    request: ModelRequest,
    model: str,
) -> ModelGatewayError:
    """Rewrite an unsupported-model failure so it names its fix.

    The provider's own message says only that the id is unknown;
    the rewrite names the calling agent, the exact id sent, where
    the id came from and the endpoint host that rejected it. The
    API key and every part of the base URL beyond the hostname are
    deliberately absent.
    """
    key = agent_key(request.metadata.get("agentId"))
    tier = request.metadata.get("modelTier")
    source = settings.model_source(key, tier)
    sent = model or request.model or "(gateway default)"
    details = {
        **error.details,
        "agent": key or "unknown",
        "model": sent,
        "source": source,
        "provider": settings.current()["provider"],
        "baseUrlHost": _base_url_host(settings),
    }
    return ModelGatewayError(
        "LLM_MODEL_NOT_SUPPORTED",
        _unsupported_model_message(sent, source, key),
        details=details,
    )


class SettingsRoutingGateway:
    """ModelGateway that follows the current settings on every call."""

    def __init__(
        self,
        settings: ModelSettings,
        fallback: ModelGateway,
        transport: HttpTransport | None = None,
        gateway_factory: Callable[
            [Mapping[str, str], HttpTransport | None],
            ModelGateway | None,
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
        model = self._settings.effective_model(
            agent_key(request.metadata.get("agentId")),
            request.metadata.get("modelTier"),
        ).strip()
        if model:
            request = request.model_copy(update={"model": model})
        try:
            return gateway.complete(request)
        except ModelGatewayError as error:
            # Name the exact model that was sent: a provider's
            # "model not supported" is unactionable without it, and
            # the effective model depends on the calling agent and
            # the run's complexity tier.
            logger.warning(
                "model call failed: agent=%s tier=%s model=%s code=%s message=%s",
                request.metadata.get("agentId"),
                request.metadata.get("modelTier"),
                model or "(gateway default)",
                error.code,
                error.message,
            )
            if error.code == "LLM_MODEL_NOT_SUPPORTED":
                raise _unsupported_model_error(
                    error,
                    self._settings,
                    request,
                    model,
                ) from error
            raise

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
