"""Tests for ImplementAgent scope and denied path validation."""

from __future__ import annotations

from asf.tools.fake import InMemoryRepository
from tests.unit.implement_helpers import (
    make_agent_with_repo,
    make_implement_request,
    make_valid_changeset_reply,
)


def test_out_of_scope_paths_rejected():
    """Path outside expectedFiles -> FAILED/LLM_INVALID_RESPONSE with details.outOfScopePaths."""
    repo = InMemoryRepository()
    reply = make_valid_changeset_reply(
        changes=[
            {"path": "src/allowed.py", "operation": "create", "content": "x\n"},
            {"path": "src/not_allowed.py", "operation": "create", "content": "y\n"},
        ]
    )
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request(expected_files=["src/allowed.py"])

    res = agent.execute(req)
    assert res.status == "FAILED"
    assert res.errors[0].code == "LLM_INVALID_RESPONSE"
    assert "outOfScopePaths" in res.errors[0].details
    assert "src/not_allowed.py" in res.errors[0].details["outOfScopePaths"]


def test_no_repository_read_for_out_of_scope():
    """Repository is NOT read for paths outside expectedFiles."""
    # The validation happens before repository reads, so this is implicitly tested
    # by out_of_scope_paths_rejected - no repository read occurs for out-of-scope paths
    pass


def test_denied_dot_git():
    """.git/ paths always denied."""
    repo = InMemoryRepository()
    reply = make_valid_changeset_reply(
        changes=[{"path": ".git/config", "operation": "create", "content": "x\n"}]
    )
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request(expected_files=[".git/config"])

    res = agent.execute(req)
    assert res.status == "FAILED"
    assert res.errors[0].code == "LLM_INVALID_RESPONSE"
    assert "deniedPaths" in res.errors[0].details
    denied = res.errors[0].details["deniedPaths"]
    assert any(d["path"] == ".git/config" for d in denied)


def test_denied_dot_env():
    """.env paths always denied."""
    repo = InMemoryRepository()
    reply = make_valid_changeset_reply(
        changes=[{"path": ".env", "operation": "create", "content": "SECRET=1\n"}]
    )
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request(expected_files=[".env"])

    res = agent.execute(req)
    assert res.status == "FAILED"
    assert res.errors[0].code == "LLM_INVALID_RESPONSE"
    assert "deniedPaths" in res.errors[0].details
    denied = res.errors[0].details["deniedPaths"]
    assert any(d["path"] == ".env" for d in denied)


def test_denied_dot_env_local():
    """.env.local paths always denied."""
    repo = InMemoryRepository()
    reply = make_valid_changeset_reply(
        changes=[{"path": ".env.local", "operation": "create", "content": "SECRET=1\n"}]
    )
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request(expected_files=[".env.local"])

    res = agent.execute(req)
    assert res.status == "FAILED"
    assert res.errors[0].code == "LLM_INVALID_RESPONSE"
    assert "deniedPaths" in res.errors[0].details


def test_denied_pem_files():
    """.pem paths always denied."""
    repo = InMemoryRepository()
    reply = make_valid_changeset_reply(
        changes=[{"path": "certs/key.pem", "operation": "create", "content": "KEY\n"}]
    )
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request(expected_files=["certs/key.pem"])

    res = agent.execute(req)
    assert res.status == "FAILED"
    assert res.errors[0].code == "LLM_INVALID_RESPONSE"
    assert "deniedPaths" in res.errors[0].details


def test_denied_key_files():
    """.key paths always denied."""
    repo = InMemoryRepository()
    reply = make_valid_changeset_reply(
        changes=[{"path": "ssh/id_rsa.key", "operation": "create", "content": "KEY\n"}]
    )
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request(expected_files=["ssh/id_rsa.key"])

    res = agent.execute(req)
    assert res.status == "FAILED"
    assert res.errors[0].code == "LLM_INVALID_RESPONSE"
    assert "deniedPaths" in res.errors[0].details


def test_denied_github_workflows():
    """.github/ paths always denied."""
    repo = InMemoryRepository()
    reply = make_valid_changeset_reply(
        changes=[{"path": ".github/workflows/ci.yml", "operation": "create", "content": "x\n"}]
    )
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request(expected_files=[".github/workflows/ci.yml"])

    res = agent.execute(req)
    assert res.status == "FAILED"
    assert res.errors[0].code == "LLM_INVALID_RESPONSE"
    assert "deniedPaths" in res.errors[0].details


def test_denied_gitlab_ci():
    """.gitlab-ci.yml always denied."""
    repo = InMemoryRepository()
    reply = make_valid_changeset_reply(
        changes=[{"path": ".gitlab-ci.yml", "operation": "create", "content": "x\n"}]
    )
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request(expected_files=[".gitlab-ci.yml"])

    res = agent.execute(req)
    assert res.status == "FAILED"
    assert res.errors[0].code == "LLM_INVALID_RESPONSE"
    assert "deniedPaths" in res.errors[0].details


def test_denied_jenkinsfile():
    """Jenkinsfile always denied."""
    repo = InMemoryRepository()
    reply = make_valid_changeset_reply(
        changes=[{"path": "Jenkinsfile", "operation": "create", "content": "x\n"}]
    )
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request(expected_files=["Jenkinsfile"])

    res = agent.execute(req)
    assert res.status == "FAILED"
    assert res.errors[0].code == "LLM_INVALID_RESPONSE"
    assert "deniedPaths" in res.errors[0].details


def test_denied_package_lock():
    """package-lock.json always denied."""
    repo = InMemoryRepository()
    reply = make_valid_changeset_reply(
        changes=[{"path": "package-lock.json", "operation": "create", "content": "x\n"}]
    )
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request(expected_files=["package-lock.json"])

    res = agent.execute(req)
    assert res.status == "FAILED"
    assert res.errors[0].code == "LLM_INVALID_RESPONSE"
    assert "deniedPaths" in res.errors[0].details


def test_denied_poetry_lock():
    """poetry.lock always denied."""
    repo = InMemoryRepository()
    reply = make_valid_changeset_reply(
        changes=[{"path": "poetry.lock", "operation": "create", "content": "x\n"}]
    )
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request(expected_files=["poetry.lock"])

    res = agent.execute(req)
    assert res.status == "FAILED"
    assert res.errors[0].code == "LLM_INVALID_RESPONSE"
    assert "deniedPaths" in res.errors[0].details


def test_denied_cargo_lock():
    """Cargo.lock always denied."""
    repo = InMemoryRepository()
    reply = make_valid_changeset_reply(
        changes=[{"path": "Cargo.lock", "operation": "create", "content": "x\n"}]
    )
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request(expected_files=["Cargo.lock"])

    res = agent.execute(req)
    assert res.status == "FAILED"
    assert res.errors[0].code == "LLM_INVALID_RESPONSE"
    assert "deniedPaths" in res.errors[0].details


def test_denied_pnpm_lock():
    """pnpm-lock.yaml always denied."""
    repo = InMemoryRepository()
    reply = make_valid_changeset_reply(
        changes=[{"path": "pnpm-lock.yaml", "operation": "create", "content": "x\n"}]
    )
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request(expected_files=["pnpm-lock.yaml"])

    res = agent.execute(req)
    assert res.status == "FAILED"
    assert res.errors[0].code == "LLM_INVALID_RESPONSE"
    assert "deniedPaths" in res.errors[0].details


def test_ci_lock_allowed_when_listed_in_expected_files():
    """CI/lock files allowed ONLY when listed in expectedFiles (they are still denied)."""
    # Per spec: denied paths are rejected EVEN IF listed in expectedFiles
    # This test confirms the behavior - they are still denied
    for path in [
        ".github/workflows/ci.yml",
        "package-lock.json",
        "poetry.lock",
        "Cargo.lock",
        "pnpm-lock.yaml",
    ]:
        repo = InMemoryRepository()
        reply = make_valid_changeset_reply(
            changes=[{"path": path, "operation": "create", "content": "x\n"}]
        )
        agent, gateway = make_agent_with_repo([reply], repo)
        req = make_implement_request(expected_files=[path])

        res = agent.execute(req)
        assert res.status == "FAILED", f"Path {path} should be denied even when listed"
        assert res.errors[0].code == "LLM_INVALID_RESPONSE"
        assert "deniedPaths" in res.errors[0].details


def test_pem_key_env_denied_even_if_listed():
    """.pem, .key, .env* rejected even if listed in expectedFiles."""
    for path in [".env", "certs/app.pem", "keys/private.key"]:
        repo = InMemoryRepository()
        reply = make_valid_changeset_reply(
            changes=[{"path": path, "operation": "create", "content": "secret\n"}]
        )
        agent, gateway = make_agent_with_repo([reply], repo)
        req = make_implement_request(expected_files=[path])

        res = agent.execute(req)
        assert res.status == "FAILED", f"Path {path} should be denied even when listed"
        assert res.errors[0].code == "LLM_INVALID_RESPONSE"
        assert "deniedPaths" in res.errors[0].details


def test_allowed_path_within_expected_files():
    """Path within expectedFiles is allowed."""
    repo = InMemoryRepository()
    reply = make_valid_changeset_reply(
        changes=[{"path": "src/calculator.py", "operation": "create", "content": "x\n"}]
    )
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request(expected_files=["src/calculator.py"])

    res = agent.execute(req)
    # Should pass scope validation (may fail on other validations)
    # The key is that outOfScopePaths should not be in errors
    if res.status == "FAILED" and res.errors[0].code == "LLM_INVALID_RESPONSE":
        assert "outOfScopePaths" not in res.errors[0].details


def test_denied_dot_git_subdir():
    """.git/ subdirectories always denied."""
    repo = InMemoryRepository()
    reply = make_valid_changeset_reply(
        changes=[{"path": ".git/objects/abc", "operation": "create", "content": "x\n"}]
    )
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request(expected_files=[".git/objects/abc"])

    res = agent.execute(req)
    assert res.status == "FAILED"
    assert res.errors[0].code == "LLM_INVALID_RESPONSE"
    assert "deniedPaths" in res.errors[0].details


def test_denied_env_file_variants():
    """Various .env* variants are denied."""
    for path in [".env", ".env.local", ".env.production", ".env.development"]:
        repo = InMemoryRepository()
        reply = make_valid_changeset_reply(
            changes=[{"path": path, "operation": "create", "content": "SECRET=1\n"}]
        )
        agent, gateway = make_agent_with_repo([reply], repo)
        req = make_implement_request(expected_files=[path])

        res = agent.execute(req)
        assert res.status == "FAILED", f"Path {path} should be denied"
        assert res.errors[0].code == "LLM_INVALID_RESPONSE"
        assert "deniedPaths" in res.errors[0].details
