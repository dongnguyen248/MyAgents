"""Hosting provider factory: profile repository -> provider (or None)."""

from __future__ import annotations

import pytest

from asf.integrations.hosting.factory import build_provider
from asf.integrations.hosting.github import GitHubProvider
from asf.integrations.hosting.gitlab import GitLabProvider
from asf.integrations.hosting.ports import HostingError
from tests.unit.test_hosting_fake import FakeTransport


def test_unconfigured_projects_return_none():
    assert build_provider(None) is None
    assert build_provider({}) is None
    assert build_provider({"provider": "git", "url": "https://x/y"}) is None
    assert build_provider({"provider": "github"}) is None  # no URL
    assert build_provider({"provider": "github", "url": "  "}) is None


def test_missing_token_is_a_loud_error():
    with pytest.raises(HostingError) as caught:
        build_provider(
            {"provider": "gitlab", "url": "https://gitlab.com/g/p"},
            environ={},
        )
    assert "ASF_GITLAB_TOKEN" in str(caught.value)


def test_gitlab_nested_groups_and_dot_git_suffix():
    transport = FakeTransport()
    transport.add("GET", "/pipelines", [])
    provider = build_provider(
        {"provider": "gitlab", "url": "https://gitlab.example.com/group/sub/proj.git"},
        environ={"ASF_GITLAB_TOKEN": "tok"},
        transport=transport,
    )
    assert isinstance(provider, GitLabProvider)
    assert provider.pipeline_status(branch="asf/t1") is None
    (call,) = transport.calls
    assert call["url"].startswith(
        "https://gitlab.example.com/api/v4/projects/group%2Fsub%2Fproj/pipelines",
    )


def test_stored_token_wins_over_environment():
    transport = FakeTransport()
    transport.add("GET", "/pipelines", [])
    provider = build_provider(
        {"provider": "gitlab", "url": "https://gitlab.example.com/g/p"},
        environ={"ASF_GITLAB_TOKEN": "env-token"},
        transport=transport,
        stored_token="stored-token",
    )
    assert isinstance(provider, GitLabProvider)
    assert provider.pipeline_status(branch="asf/t1") is None
    (call,) = transport.calls
    assert call["headers"]["PRIVATE-TOKEN"] == "stored-token"


def test_stored_token_alone_satisfies_the_token_requirement():
    provider = build_provider(
        {"provider": "gitlab", "url": "https://gitlab.example.com/g/p"},
        environ={},
        transport=FakeTransport(),
        stored_token="stored-token",
    )
    assert isinstance(provider, GitLabProvider)


def test_github_com_and_enterprise_api_bases():
    transport = FakeTransport()
    transport.add("GET", "/check-runs", {"total_count": 0, "check_runs": []})
    transport.add("GET", "/status", {"state": "pending", "total_count": 0})
    provider = build_provider(
        {"provider": "github", "url": "https://github.com/octo/demo"},
        environ={"ASF_GITHUB_TOKEN": "tok"},
        transport=transport,
    )
    assert isinstance(provider, GitHubProvider)
    provider.pipeline_status(branch="asf/t1")
    assert transport.calls[0]["url"].startswith(
        "https://api.github.com/repos/octo/demo/commits/",
    )

    enterprise = build_provider(
        {"provider": "github", "url": "https://ghe.example.com/octo/demo"},
        environ={"ASF_GITHUB_TOKEN": "tok"},
        transport=FakeTransport(),
    )
    assert isinstance(enterprise, GitHubProvider)


def test_custom_token_env_and_bad_urls():
    provider = build_provider(
        {
            "provider": "gitlab",
            "url": "https://gitlab.com/g/p",
            "tokenEnv": "MY_LAB_TOKEN",
        },
        environ={"MY_LAB_TOKEN": "tok"},
        transport=FakeTransport(),
    )
    assert isinstance(provider, GitLabProvider)
    with pytest.raises(HostingError):
        build_provider(
            {"provider": "github", "url": "not-a-url"},
            environ={"ASF_GITHUB_TOKEN": "tok"},
        )
    with pytest.raises(HostingError):
        build_provider(
            {"provider": "github", "url": "https://github.com/onlyowner"},
            environ={"ASF_GITHUB_TOKEN": "tok"},
        )
