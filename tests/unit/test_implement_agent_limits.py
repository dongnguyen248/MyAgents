"""Tests for ImplementAgent limits, NUL bytes, whitespace, duplicates, empty changeset, secrets."""

from __future__ import annotations

from asf.tools.fake import InMemoryRepository
from tests.unit._fake_secrets import fake_secret
from tests.unit.implement_helpers import (
    make_agent_with_repo,
    make_implement_request,
    make_valid_changeset_reply,
)


def test_max_changes_limit() -> None:
    """MAX_CHANGES_PER_CHANGESET limit enforced."""
    from asf.agents._shared.limits import MAX_CHANGES_PER_CHANGESET

    repo = InMemoryRepository()
    num_changes = MAX_CHANGES_PER_CHANGESET + 1
    changes = [
        {"path": f"src/file{i}.py", "operation": "create", "content": f"# File {i}\n"}
        for i in range(num_changes)
    ]
    expected_files = [f"src/file{i}.py" for i in range(num_changes)]
    reply = make_valid_changeset_reply(changes=changes)
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request(expected_files=expected_files)

    res = agent.execute(req)
    assert res.status == "FAILED"
    assert res.errors[0].code == "LLM_INVALID_RESPONSE"
    assert "limitIssues" in res.errors[0].details
    assert any("exceeds limit" in issue for issue in res.errors[0].details["limitIssues"])


def test_max_chars_per_file_limit() -> None:
    """MAX_FILE_SIZE_BYTES limit per file enforced."""
    from asf.agents._shared.limits import MAX_FILE_SIZE_BYTES

    repo = InMemoryRepository()
    large_content = "x" * (MAX_FILE_SIZE_BYTES + 100)
    reply = make_valid_changeset_reply(
        changes=[{"path": "src/large.py", "operation": "create", "content": large_content}]
    )
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request(expected_files=["src/large.py"])

    res = agent.execute(req)
    assert res.status == "FAILED"
    assert res.errors[0].code == "LLM_INVALID_RESPONSE"
    assert "contentIssues" in res.errors[0].details
    issues = res.errors[0].details["contentIssues"]
    assert any("exceeds limit" in issue.get("issue", "") for issue in issues)


def test_max_total_chars_limit() -> None:
    """MAX_TOTAL_CONTENT_BYTES limit enforced."""
    from asf.agents.implement.agent import MAX_CODE_REPLY_CHARS

    repo = InMemoryRepository()
    # Create a reply that exceeds MAX_CODE_REPLY_CHARS (500K) to test raw reply limit
    # The changeset total content limit (1MB) is higher than raw reply limit (500K)
    # so raw reply limit triggers first
    per_file = 300_000
    changes = [
        {"path": f"src/file{i}.py", "operation": "create", "content": "x" * per_file}
        for i in range(2)
    ]
    reply = make_valid_changeset_reply(changes=changes)
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request(expected_files=[f"src/file{i}.py" for i in range(2)])

    res = agent.execute(req)
    assert res.status == "FAILED"
    assert res.errors[0].code == "LLM_INVALID_RESPONSE"
    # Raw reply size limit triggers first (lower limit)
    assert "charCount" in res.errors[0].details
    assert "limit" in res.errors[0].details
    assert res.errors[0].details["limit"] == MAX_CODE_REPLY_CHARS


def test_nul_bytes_rejected() -> None:
    """NUL bytes in content rejected."""
    repo = InMemoryRepository()
    nul_content = "print('hello\x00world')\n"
    reply = make_valid_changeset_reply(
        changes=[{"path": "src/test.py", "operation": "create", "content": nul_content}]
    )
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request(expected_files=["src/test.py"])

    res = agent.execute(req)
    assert res.status == "FAILED"
    assert res.errors[0].code == "LLM_INVALID_RESPONSE"
    assert "contentIssues" in res.errors[0].details
    issues = res.errors[0].details["contentIssues"]
    assert any("NUL" in issue.get("issue", "") for issue in issues)


def test_whitespace_only_content_rejected() -> None:
    """Whitespace-only content rejected."""
    repo = InMemoryRepository()
    reply = make_valid_changeset_reply(
        changes=[{"path": "src/test.py", "operation": "create", "content": "   \n\t  \n"}]
    )
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request(expected_files=["src/test.py"])

    res = agent.execute(req)
    assert res.status == "FAILED"
    assert res.errors[0].code == "LLM_INVALID_RESPONSE"
    assert "contentIssues" in res.errors[0].details
    issues = res.errors[0].details["contentIssues"]
    assert any("whitespace-only" in issue.get("issue", "") for issue in issues)


def test_duplicate_paths_in_changeset_rejected() -> None:
    """Duplicate paths in changeset rejected."""
    repo = InMemoryRepository()
    reply = make_valid_changeset_reply(
        changes=[
            {"path": "src/test.py", "operation": "create", "content": "a\n"},
            {"path": "src/test.py", "operation": "modify", "content": "b\n"},
        ]
    )
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request(expected_files=["src/test.py"])

    res = agent.execute(req)
    assert res.status == "FAILED"
    assert res.errors[0].code == "LLM_INVALID_RESPONSE"
    assert "validationError" in res.errors[0].details
    assert any("duplicate" in str(res.errors[0].details["validationError"]).lower() for _ in [0])


def test_empty_change_set_rejected() -> None:
    """Empty change set rejected."""
    repo = InMemoryRepository()
    reply = make_valid_changeset_reply(changes=[])
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request()

    res = agent.execute(req)
    assert res.status == "FAILED"
    assert res.errors[0].code == "LLM_INVALID_RESPONSE"
    assert "validationError" in res.errors[0].details
    assert any("empty" in str(res.errors[0].details["validationError"]).lower() for _ in [0])


def test_secret_scanning_api_key() -> None:
    """API keys in generated content detected and rejected."""
    repo = InMemoryRepository()
    secret_content = 'API_KEY = "sk-1234567890abcdef1234567890abcdef"\n'
    reply = make_valid_changeset_reply(
        changes=[{"path": "src/config.py", "operation": "create", "content": secret_content}]
    )
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request(expected_files=["src/config.py"])

    res = agent.execute(req)
    assert res.status == "FAILED"
    assert res.errors[0].code == "LLM_INVALID_RESPONSE"
    assert "secretIssues" in res.errors[0].details
    issues = res.errors[0].details["secretIssues"]
    assert len(issues) > 0
    assert issues[0]["path"] == "src/config.py"
    # Secret value should never appear in details
    dumped = str(res.errors[0].details)
    assert "sk-1234567890abcdef1234567890abcdef" not in dumped


def test_secret_scanning_aws_key() -> None:
    """AWS access keys detected and rejected."""
    repo = InMemoryRepository()
    secret_content = f'AWS_ACCESS_KEY_ID = "{fake_secret("aws_access")}"\n'
    reply = make_valid_changeset_reply(
        changes=[{"path": "src/aws.py", "operation": "create", "content": secret_content}]
    )
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request(expected_files=["src/aws.py"])

    res = agent.execute(req)
    assert res.status == "FAILED"
    assert res.errors[0].code == "LLM_INVALID_RESPONSE"
    assert "secretIssues" in res.errors[0].details
    dumped = str(res.errors[0].details)
    assert fake_secret("aws_access") not in dumped


def test_secret_scanning_private_key() -> None:
    """Private keys detected and rejected."""
    repo = InMemoryRepository()
    secret_content = """-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEA...
-----END RSA PRIVATE KEY-----"""
    reply = make_valid_changeset_reply(
        changes=[{"path": "ssh/id_rsa", "operation": "create", "content": secret_content}]
    )
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request(expected_files=["ssh/id_rsa"])

    res = agent.execute(req)
    assert res.status == "FAILED"
    assert res.errors[0].code == "LLM_INVALID_RESPONSE"
    assert "secretIssues" in res.errors[0].details
    dumped = str(res.errors[0].details)
    assert "PRIVATE KEY" not in dumped


def test_secret_scanning_jwt() -> None:
    """JWT tokens detected and rejected."""
    repo = InMemoryRepository()
    # JWT token split to avoid line length limit
    jwt_part1 = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    jwt_part2 = "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ"
    jwt_part3 = "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    jwt_token = f"{jwt_part1}.{jwt_part2}.{jwt_part3}"
    secret_content = f'token = "{jwt_token}"\n'
    reply = make_valid_changeset_reply(
        changes=[{"path": "src/auth.py", "operation": "create", "content": secret_content}]
    )
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request(expected_files=["src/auth.py"])

    res = agent.execute(req)
    assert res.status == "FAILED"
    assert res.errors[0].code == "LLM_INVALID_RESPONSE"
    assert "secretIssues" in res.errors[0].details
    dumped = str(res.errors[0].details)
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in dumped


def test_secret_scanning_generic_password() -> None:
    """Generic password patterns detected."""
    repo = InMemoryRepository()
    secret_content = 'password = "supersecretpassword123"\n'
    reply = make_valid_changeset_reply(
        changes=[{"path": "src/config.py", "operation": "create", "content": secret_content}]
    )
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request(expected_files=["src/config.py"])

    res = agent.execute(req)
    assert res.status == "FAILED"
    assert res.errors[0].code == "LLM_INVALID_RESPONSE"
    assert "secretIssues" in res.errors[0].details
    dumped = str(res.errors[0].details)
    assert "supersecretpassword123" not in dumped


def test_secret_details_contain_pattern_and_path_not_value() -> None:
    """Secret details contain pattern names and paths, never the secret value."""
    repo = InMemoryRepository()
    secret_content = 'API_KEY = "sk-test123"\n'
    reply = make_valid_changeset_reply(
        changes=[{"path": "src/config.py", "operation": "create", "content": secret_content}]
    )
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request(expected_files=["src/config.py"])

    res = agent.execute(req)
    assert res.status == "FAILED"
    issues = res.errors[0].details["secretIssues"]
    assert len(issues) > 0
    issue = issues[0]
    assert "path" in issue
    assert "pattern" in issue
    assert issue["path"] == "src/config.py"
    # Verify secret value is not in the serialized result
    import json
    dumped = json.dumps(res.to_contract())
    assert "sk-test123" not in dumped