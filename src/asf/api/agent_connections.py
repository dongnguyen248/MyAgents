"""Per-agent connection profiles for the model settings record.

The shared settings give every agent the same provider, endpoint and
key. A connection profile lets ONE agent override the transport-level
half of that: its own provider, base URL, API key, extra headers and
timeout. Model selection stays with ``agentModels`` - a profile never
names a model. An agent without a profile, or a field the profile
leaves unset, inherits the shared settings, so existing agents keep
working unchanged.

Profiles persist inside ``model-settings.json`` under
``agentConnections``, keyed by agent type like ``agentModels``. The
public view masks the key (configured + last-4 hint) and every header
value (``****``): header values can carry tokens, so they are
write-only through the API, exactly like the key.

URL policy (operator decision, 2026-11-23): the URL must parse with
an http/https scheme and a host. Localhost and private addresses are
ALLOWED - the operator's real routes are local proxies - but the
cloud metadata address 169.254.169.254 is blocked, and plain http is
flagged in the public view as a soft warning, not an error.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Collection, Mapping
from typing import Any, NamedTuple
from urllib.parse import urlsplit

__all__ = [
    "clean_connections",
    "effective_settings",
    "load_connections",
    "public_connections",
    "stored_connections",
]

BLOCKED_HOST = "169.254.169.254"
MAX_HEADERS = 20
MAX_HEADER_VALUE_CHARS = 500
MIN_TIMEOUT_SECONDS = 1
MAX_TIMEOUT_SECONDS = 3600
MASKED = "****"

#: Headers the provider adapters set themselves; a profile may not
#: override them (auth has its own field: the profile's API key).
RESERVED_HEADERS = frozenset({"authorization", "content-type", "host", "x-goog-api-key"})

_HEADER_NAME = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_PROFILE_FIELDS = frozenset({"provider", "baseUrl", "apiKey", "headers", "timeoutSeconds"})

type Profile = dict[str, Any]


def _empty_profile() -> Profile:
    return {"provider": "", "baseUrl": "", "apiKey": "", "headers": {}, "timeoutSeconds": None}


def _is_empty(profile: Profile) -> bool:
    return not (
        profile["provider"]
        or profile["baseUrl"]
        or profile["apiKey"]
        or profile["headers"]
        or profile["timeoutSeconds"] is not None
    )


def load_connections(
    raw: Any,
    known_agents: Collection[str],
    providers: Collection[str],
) -> dict[str, Profile]:
    """Stored profiles, normalised on load; never raises.

    Entries for unknown agents or with malformed fields are skipped
    or sanitised field by field, so one corrupt entry cannot brick
    the settings.
    """
    if not isinstance(raw, Mapping):
        return {}
    cleaned: dict[str, Profile] = {}
    for key, value in raw.items():
        if key not in known_agents or not isinstance(value, Mapping):
            continue
        profile = _sanitize_profile(value, providers)
        if not _is_empty(profile):
            cleaned[str(key)] = profile
    return cleaned


def _sanitize_profile(raw: Mapping[str, Any], providers: Collection[str]) -> Profile:
    profile = _empty_profile()
    for field in ("provider", "baseUrl", "apiKey"):
        if isinstance(raw.get(field), str):
            profile[field] = raw[field].strip()
    if profile["provider"] not in providers:
        profile["provider"] = ""
    profile["headers"] = _sanitize_headers(raw.get("headers"))
    profile["timeoutSeconds"] = _sanitize_timeout(raw.get("timeoutSeconds"))
    return profile


def _sanitize_headers(raw: Any) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        return {}
    return {
        str(name): value
        for name, value in raw.items()
        if isinstance(value, str) and _HEADER_NAME.match(str(name))
    }


def _sanitize_timeout(raw: Any) -> int | None:
    if isinstance(raw, bool) or not isinstance(raw, int):
        return None
    if MIN_TIMEOUT_SECONDS <= raw <= MAX_TIMEOUT_SECONDS:
        return raw
    return None


class CleanContext(NamedTuple):
    """What strict cleaning needs to know about the settings record."""

    existing: Mapping[str, Profile]
    known_agents: Collection[str]
    providers: Collection[str]
    key_of: Callable[[Any], str | None]


def clean_connections(raw: Any, context: CleanContext) -> dict[str, Profile]:
    """Validate a PUT payload's agentConnections (strict; raises).

    A null or empty profile removes the agent's override. The API key
    is write-only like the shared key: omitting ``apiKey`` keeps the
    stored one, ``clearKey: true`` drops it, a string replaces it.
    """
    if raw is None:
        return {name: dict(profile) for name, profile in context.existing.items()}
    if not isinstance(raw, Mapping):
        raise ValueError("agentConnections must be an object keyed by agent")
    cleaned = {name: dict(profile) for name, profile in context.existing.items()}
    for key, value in raw.items():
        _clean_entry(cleaned, key, value, context)
    return {name: p for name, p in cleaned.items() if not _is_empty(p)}


def _clean_entry(
    cleaned: dict[str, Profile],
    key: Any,
    value: Any,
    context: CleanContext,
) -> None:
    name = context.key_of(key)
    if name is None:
        raise ValueError(
            f"Unknown agent {key!r} in agentConnections; "
            f"expected one of {', '.join(sorted(context.known_agents))}",
        )
    if value is None or value == {}:
        cleaned.pop(name, None)
        return
    cleaned[name] = _clean_profile(name, value, cleaned.get(name), context.providers)


def _clean_profile(
    name: str,
    raw: Any,
    existing: Profile | None,
    providers: Collection[str],
) -> Profile:
    if not isinstance(raw, Mapping):
        raise ValueError(f"agentConnections.{name} must be an object")
    unknown = set(raw) - _PROFILE_FIELDS - {"clearKey"}
    if unknown:
        raise ValueError(f"agentConnections.{name} has unknown fields: {sorted(unknown)}")
    profile = dict(existing) if existing is not None else _empty_profile()
    _clean_text_fields(name, raw, profile, providers)
    if "headers" in raw:
        profile["headers"] = _clean_headers(name, raw["headers"])
    if "timeoutSeconds" in raw:
        profile["timeoutSeconds"] = _clean_timeout(name, raw["timeoutSeconds"])
    if raw.get("clearKey") is True:
        profile["apiKey"] = ""
    return profile


def _clean_text_fields(
    name: str,
    raw: Mapping[str, Any],
    profile: Profile,
    providers: Collection[str],
) -> None:
    for field in ("provider", "baseUrl", "apiKey"):
        if field not in raw:
            continue
        value = raw[field]
        if not isinstance(value, str):
            raise ValueError(f"agentConnections.{name}.{field} must be a string")
        profile[field] = value.strip()
    if profile["provider"] and profile["provider"] not in providers:
        raise ValueError(
            f"Unknown model provider {profile['provider']!r} in agentConnections.{name}; "
            f"expected one of {', '.join(sorted(providers))}",
        )
    if profile["baseUrl"]:
        _check_base_url(name, profile["baseUrl"])


def _check_base_url(name: str, url: str) -> None:
    try:
        parts = urlsplit(url)
        host = parts.hostname
        scheme = parts.scheme
    except ValueError:
        host, scheme = None, ""
    if scheme not in ("http", "https") or not host:
        raise ValueError(
            f"agentConnections.{name}.baseUrl must be an http(s) URL with a host",
        )
    if host == BLOCKED_HOST:
        raise ValueError(
            f"agentConnections.{name}.baseUrl must not point at the cloud metadata address",
        )


def _clean_headers(name: str, raw: Any) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        raise ValueError(f"agentConnections.{name}.headers must be an object")
    if len(raw) > MAX_HEADERS:
        raise ValueError(f"agentConnections.{name}.headers allows at most {MAX_HEADERS} entries")
    cleaned: dict[str, str] = {}
    for header, value in raw.items():
        cleaned[_clean_header_name(name, header)] = _clean_header_value(name, header, value)
    return cleaned


def _clean_header_name(name: str, header: Any) -> str:
    if not isinstance(header, str) or not _HEADER_NAME.match(header):
        raise ValueError(f"agentConnections.{name}.headers has an invalid header name {header!r}")
    if header.lower() in RESERVED_HEADERS:
        raise ValueError(
            f"agentConnections.{name}.headers may not set {header!r}; "
            "the adapter sets it (use the API key field for auth)",
        )
    return header


def _clean_header_value(name: str, header: str, value: Any) -> str:
    if not isinstance(value, str) or "\r" in value or "\n" in value:
        raise ValueError(f"agentConnections.{name}.headers.{header} must be a single-line string")
    if len(value) > MAX_HEADER_VALUE_CHARS:
        raise ValueError(f"agentConnections.{name}.headers.{header} is too long")
    return value


def _clean_timeout(name: str, raw: Any) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError(f"agentConnections.{name}.timeoutSeconds must be an integer")
    if not MIN_TIMEOUT_SECONDS <= raw <= MAX_TIMEOUT_SECONDS:
        raise ValueError(
            f"agentConnections.{name}.timeoutSeconds must be between "
            f"{MIN_TIMEOUT_SECONDS} and {MAX_TIMEOUT_SECONDS}",
        )
    return raw


def public_connections(connections: Mapping[str, Profile]) -> dict[str, Any]:
    """The masked public view: key hint only, header values masked."""
    return {name: _public_profile(profile) for name, profile in connections.items()}


def _public_profile(profile: Profile) -> dict[str, Any]:
    key = profile["apiKey"]
    return {
        "provider": profile["provider"],
        "baseUrl": profile["baseUrl"],
        "keyConfigured": bool(key),
        "keyHint": f"…{key[-4:]}" if len(key) >= 4 else "",
        "headers": {name: MASKED for name in profile["headers"]},
        "timeoutSeconds": profile["timeoutSeconds"],
        "insecureHttp": profile["baseUrl"].startswith("http://"),
    }


def stored_connections(connections: Mapping[str, Profile]) -> dict[str, Any]:
    """The persisted form: full profiles (keys included), empties out."""
    return {
        name: {**profile, "headers": dict(profile["headers"])}
        for name, profile in connections.items()
        if not _is_empty(profile)
    }


def effective_settings(shared: Mapping[str, str], profile: Profile | None) -> dict[str, Any]:
    """The gateway-factory input for one agent: shared, overridden
    field by field by the agent's profile where the profile sets a
    value; headers and timeout ride along for the factory."""
    effective: dict[str, Any] = dict(shared)
    effective["headers"] = {}
    effective["timeoutSeconds"] = None
    if profile is None:
        return effective
    for field in ("provider", "baseUrl", "apiKey"):
        if profile[field]:
            effective[field] = profile[field]
    effective["headers"] = dict(profile["headers"])
    effective["timeoutSeconds"] = profile["timeoutSeconds"]
    return effective
