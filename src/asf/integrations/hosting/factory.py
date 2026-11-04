"""Build a hosting provider from a project profile's ``repository``.

The profile carries the provider name and the repository URL — the
"set link" a user pastes when configuring a project — and may name the
environment variable holding the access token via ``tokenEnv``
(defaults: ``ASF_GITLAB_TOKEN`` / ``ASF_GITHUB_TOKEN``). The token
itself is never stored in the profile.

Returns None when the project has no usable hosting configuration
(unknown provider or no URL): callers treat that as "hosting not
configured" and keep the previous no-op behavior. Raises
:class:`HostingError` when hosting *is* configured but unusable (bad
URL, missing token), so the failure is loud instead of silent.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from asf.integrations.hosting.github import GitHubProvider
from asf.integrations.hosting.gitlab import GitLabProvider
from asf.integrations.hosting.http import Transport
from asf.integrations.hosting.ports import HostingError, HostingProvider

__all__ = ["build_provider", "DEFAULT_TOKEN_ENVS"]

DEFAULT_TOKEN_ENVS = {"gitlab": "ASF_GITLAB_TOKEN", "github": "ASF_GITHUB_TOKEN"}


def build_provider(
    repository: Mapping[str, Any] | None,
    environ: Mapping[str, str] | None = None,
    transport: Transport | None = None,
) -> HostingProvider | None:
    if not isinstance(repository, Mapping):
        return None
    provider_name = str(repository.get("provider") or "").strip().lower()
    if provider_name not in DEFAULT_TOKEN_ENVS:
        return None
    url = str(repository.get("url") or "").strip()
    if not url:
        return None
    parsed = urlsplit(url)
    if parsed.scheme not in ("https", "http") or not parsed.hostname:
        raise HostingError(
            f"Repository URL is not a valid http(s) URL: {url!r}",
        )
    path = parsed.path.strip("/")
    if path.endswith(".git"):
        path = path[: -len(".git")]
    if not path:
        raise HostingError(f"Repository URL has no project path: {url!r}")

    env = os.environ if environ is None else environ
    token_env = str(repository.get("tokenEnv") or DEFAULT_TOKEN_ENVS[provider_name])
    token = env.get(token_env) or None
    if token is None:
        raise HostingError(
            f"No access token for the {provider_name} provider: set the "
            f"{token_env} environment variable on the backend "
            "(the profile names it via repository.tokenEnv; never store "
            "the token itself in the profile).",
        )

    origin = f"{parsed.scheme}://{parsed.netloc}"
    if provider_name == "gitlab":
        return GitLabProvider(f"{origin}/api/v4", path, token, transport)
    segments = path.split("/")
    if len(segments) != 2:
        raise HostingError(
            f"GitHub repository URL must look like <host>/<owner>/<repo>: {url!r}",
        )
    api_base = (
        "https://api.github.com"
        if parsed.hostname == "github.com"
        else f"{origin}/api/v3"
    )
    return GitHubProvider(api_base, segments[0], segments[1], token, transport)
