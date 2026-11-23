"""Builds the real provider gateway for a settings mapping.

Split out of :mod:`asf.api.model_settings` (which re-exports
:func:`build_configured_gateway` for compatibility) so the settings
record stays small. The input is the shared settings dict or one
agent's effective settings from
:func:`asf.api.agent_connections.effective_settings`; on top of the
provider/model/baseUrl/apiKey fields it may carry a connection
profile's extras: ``headers`` (merged into every request at the
transport seam) and ``timeoutSeconds`` (the per-attempt timeout).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, NamedTuple

from asf.integrations.gemini import GeminiModelGateway
from asf.integrations.gemini import UrlLibTransport as GeminiUrlLibTransport
from asf.integrations.header_transport import HeaderInjectingTransport
from asf.integrations.openai_compatible import (
    HttpTransport,
    OpenAICompatibleGateway,
    UrlLibTransport,
)
from asf.models.ports import ModelGateway

__all__ = ["DEFAULT_BASE_URLS", "build_configured_gateway"]

DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "github-models": "https://models.github.ai/inference",
    "meta": "https://api.meta.ai/v1",
}

_DEFAULT_TIMEOUT_SECONDS = 300.0


def build_configured_gateway(
    settings: Mapping[str, Any],
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
    injected = _header_transport(settings, transport, provider)
    timeout = _profile_timeout(settings)
    if provider == "gemini":
        return _build_gemini(settings, _GatewayArgs(model, api_key, injected, timeout))
    base_url = (settings.get("baseUrl") or "").strip() or DEFAULT_BASE_URLS.get(
        provider,
        "",
    )
    return OpenAICompatibleGateway(
        base_url=base_url,
        model=model,
        api_key=api_key,
        transport=injected if injected is not None else transport,
        timeout_seconds=timeout if timeout is not None else _DEFAULT_TIMEOUT_SECONDS,
        # Anthropic's OpenAI-compatible endpoint understands
        # cache_control content parts; enable the agents' cache
        # prefix hint only there.
        prompt_cache="anthropic" in base_url,
    )


def _profile_timeout(settings: Mapping[str, Any]) -> float | None:
    raw = settings.get("timeoutSeconds")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or raw <= 0:
        return None
    return float(raw)


def _header_transport(
    settings: Mapping[str, Any],
    transport: HttpTransport | None,
    provider: str,
) -> HeaderInjectingTransport | None:
    """The profile's headers as a transport wrapper, if it has any.

    Wraps the caller's transport when one was given, else the
    provider's own default transport. None means the profile carries
    no headers and every gateway keeps its current transport.
    """
    headers = settings.get("headers")
    if not isinstance(headers, Mapping) or not headers:
        return None
    inner: Any = transport
    if inner is None:
        inner = GeminiUrlLibTransport() if provider == "gemini" else UrlLibTransport()
    cleaned = {str(name): str(value) for name, value in headers.items()}
    return HeaderInjectingTransport(inner, cleaned)


class _GatewayArgs(NamedTuple):
    model: str
    api_key: str
    injected: HeaderInjectingTransport | None
    timeout: float | None


def _build_gemini(
    settings: Mapping[str, Any],
    args: _GatewayArgs,
) -> GeminiModelGateway:
    kwargs: dict[str, Any] = {"model": args.model, "api_key": args.api_key}
    base_url = (settings.get("baseUrl") or "").strip()
    if base_url:
        kwargs["endpoint"] = base_url
    if args.injected is not None:
        kwargs["transport"] = args.injected
    if args.timeout is not None:
        kwargs["timeout_seconds"] = args.timeout
    return GeminiModelGateway(**kwargs)
