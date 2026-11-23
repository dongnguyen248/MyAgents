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

A second, transport-level override layer lives in
:mod:`asf.api.agent_connections`: **per-agent connection profiles**
(``agentConnections``) give one agent its own provider, base URL, API
key, extra headers and timeout, inherited field by field from the
shared settings when unset.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from asf.api.agent_connections import (
    CleanContext,
    Profile,
    check_profiles,
    clean_connections,
    load_connections,
    public_connections,
    stored_connections,
)
from asf.api.agent_connections import effective_settings as merge_connection
from asf.api.configured_gateway import DEFAULT_BASE_URLS, build_configured_gateway
from asf.api.model_ids import checked_model_id, normalize_stored_model_id
from asf.contracts.map_events import endpoint_label
from asf.contracts.models import ModelMessage, ModelRequest, ModelResponse
from asf.integrations.openai_compatible import (
    HttpTransport,
)
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

#: Agents that call a model and may carry a per-agent model override.
#: Test (no model calls) and the decomposer (complex tier: always the
#: shared model) are absent. Test-all cap: len(MODEL_AGENTS) + 1.
MODEL_AGENTS = ("spec", "plan", "task", "implement", "review", "fix", "artifact-review")


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


def _load_overrides(
    stored: Mapping[str, Any],
) -> tuple[dict[str, str], dict[str, Profile]]:
    models = _load_agent_models(stored.get("agentModels"))
    connections = load_connections(stored.get("agentConnections"), MODEL_AGENTS, PROVIDERS)
    return models, connections


def _clean_field_value(field: str, value: str) -> str:
    """The stored form of a settings text field (model ids are checked)."""
    if field == "model":
        return checked_model_id("model", value)
    return value.strip()


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
        self._agent_connections: dict[str, Profile] = {}
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
                self._agent_models, self._agent_connections = _load_overrides(stored)

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

    def agent_connections(self) -> dict[str, Profile]:
        """Per-agent connection profiles (agent type -> profile)."""
        return {
            name: {**profile, "headers": dict(profile["headers"])}
            for name, profile in self._agent_connections.items()
        }

    def effective_settings(self, agent: str | None = None) -> dict[str, Any]:
        """Gateway-factory input for one agent: the shared settings
        overridden field by field by the agent's connection profile,
        with the profile's headers and timeout riding along."""
        key = agent_key(agent)
        profile = self._agent_connections.get(key) if key is not None else None
        return merge_connection(self._data, profile)

    def provider_host(self, agent: str | None = None) -> tuple[str, str]:
        """The effective provider and endpoint hostname for an agent -
        the two facts an error detail may carry about the endpoint."""
        effective = self.effective_settings(agent)
        return str(effective["provider"]), _host_of(effective)

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
            "agentConnections": public_connections(self._agent_connections),
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
        agent_models, agent_connections = self._clean_overrides(payload)
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
        self._check_profiles(agent_connections, data)
        self._data = data
        self._agent_models, self._agent_connections = agent_models, agent_connections
        self._persist()
        return self.public()

    def _clean_overrides(
        self,
        payload: Mapping[str, Any],
    ) -> tuple[dict[str, str], dict[str, Profile]]:
        agent_models = self._agent_models
        if "agentModels" in payload:
            agent_models = self._clean_agent_models(payload["agentModels"], strict=True)
        connections = self._agent_connections
        if "agentConnections" in payload:
            context = CleanContext(connections, MODEL_AGENTS, PROVIDERS, agent_key)
            connections = clean_connections(payload["agentConnections"], context)
        return agent_models, connections

    def _check_profiles(
        self,
        connections: dict[str, Profile],
        data: dict[str, str],
    ) -> None:
        check_profiles(connections, data)

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
        settings = self.effective_settings(agent_key(agent))
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
            request = ModelRequest(
                messages=[ModelMessage(role="user", content="Reply with the single word OK")],
                model=self.effective_model(agent_name) or None,
            )
            response = gateway.complete(request)
        except ModelGatewayError as error:
            return {"ok": False, "message": error.message}
        except Exception as error:  # transport-level surprises
            return {"ok": False, "message": f"{type(error).__name__}: {error}"}
        if response.content.strip():
            return {
                "ok": True,
                "message": f"Provider answered with model '{response.model}': "
                f"{response.content.strip()[:80]!r} — reachability and the "
                "model id only; a full agent request can still be rejected.",
            }
        return {"ok": False, "message": "Provider answered with empty content."}

    def _persist(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        record: dict[str, Any] = dict(self._data)
        record["agentModels"] = dict(self._agent_models)
        record["agentConnections"] = stored_connections(self._agent_connections)
        self._path.write_text(
            json.dumps(record, indent=2),
            encoding="utf-8",
        )


def _host_of(current: Mapping[str, Any]) -> str:
    """The endpoint's hostname only, for error details and logs.

    Never the credentials, port, path or query of the URL: an error
    detail is shown on dashboards and stored on runs, so it carries
    just enough to recognise which endpoint rejected the model.
    """
    try:
        return urlsplit(_base_url_of(current)).hostname or ""
    except ValueError:
        return ""


def _base_url_of(current: Mapping[str, Any]) -> str:
    base = str(current.get("baseUrl") or "").strip()
    return base or DEFAULT_BASE_URLS.get(str(current.get("provider") or ""), "")


def _endpoint_label_of(current: Mapping[str, Any]) -> str | None:
    """The endpoint's host:port label for the live map, or None.

    Display-only: the map may tell two local proxies apart by port,
    but the credentials, path and query of the URL never leave the
    settings layer.
    """
    label = endpoint_label(_base_url_of(current))
    return label or None


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
    provider, host = settings.provider_host(key)
    details = {
        **error.details,
        "agent": key or str(request.metadata.get("agentId") or "unknown"),
        "model": sent,
        "source": source,
        "provider": provider,
        "baseUrlHost": host,
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
            [Mapping[str, Any], HttpTransport | None],
            ModelGateway | None,
        ] = build_configured_gateway,
    ) -> None:
        self._settings = settings
        self._fallback = fallback
        self._transport = transport
        self._factory = gateway_factory
        self._cache: dict[str, ModelGateway | None] = {}

    def endpoint_label(self, agent_id: str | None) -> str | None:
        """The live map's label for this agent's endpoint: host:port."""
        key = agent_key(agent_id)
        return _endpoint_label_of(self._settings.effective_settings(key))

    def complete(self, request: ModelRequest) -> ModelResponse:
        key = agent_key(request.metadata.get("agentId"))
        effective = self._settings.effective_settings(key)
        gateway = self._resolve(effective)
        if gateway is None:
            return self._fallback.complete(request)
        model = self._settings.effective_model(
            key,
            request.metadata.get("modelTier"),
        ).strip()
        if model:
            request = request.model_copy(update={"model": model})
        try:
            return gateway.complete(request)
        except ModelGatewayError as error:
            self._log_failure(request, effective, model, error)
            if error.code == "LLM_MODEL_NOT_SUPPORTED":
                raise _unsupported_model_error(
                    error,
                    self._settings,
                    request,
                    model,
                ) from error
            raise

    def _log_failure(
        self,
        request: ModelRequest,
        effective: dict[str, Any],
        model: str,
        error: ModelGatewayError,
    ) -> None:
        # Name the exact model that was sent: a provider's "model not
        # supported" is unactionable without it, and the effective
        # model depends on the calling agent and the run's complexity
        # tier. The endpoint is named by provider + host only - never
        # the key, the headers or the rest of the URL.
        logger.warning(
            "model call failed: agent=%s tier=%s model=%s provider=%s host=%s code=%s message=%s",
            request.metadata.get("agentId"),
            request.metadata.get("modelTier"),
            model or "(gateway default)",
            effective["provider"],
            _host_of(effective),
            error.code,
            error.message,
        )

    def _resolve(self, effective: dict[str, Any]) -> ModelGateway | None:
        fingerprint = json.dumps(effective, sort_keys=True, default=str)
        if fingerprint in self._cache:
            return self._cache[fingerprint]
        try:
            gateway = self._factory(effective, self._transport)
        except (ValueError, ModelGatewayError) as error:
            raise ModelGatewayError(
                "INTEGRATION_UNAVAILABLE",
                f"Configured model provider is unusable: {error}",
            ) from None
        self._cache[fingerprint] = gateway
        return gateway
