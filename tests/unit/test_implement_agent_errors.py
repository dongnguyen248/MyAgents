"""Tests for ImplementAgent error handling (repository, gateway, invalid replies)."""

from __future__ import annotations

import json

from asf.tools.fake import InMemoryRepository
from tests.unit.implement_helpers import (
    ModelErrorGateway,
    RateLimitGateway,
    TimeoutGateway,
    TooLargeRepository,
    UnexpectedErrorGateway,
    make_agent_with_gateway,
    make_agent_with_repo,
    make_implement_request,
    make_valid_changeset_reply,
)


def test_existing_file_too_large_rejected() -> None:
    """Existing file too large -> REJECTED/VALIDATION_FAILED and gateway NOT called."""
    repo = TooLargeRepository()
    reply = make_valid_changeset_reply(
        changes=[{"path": "src/existing.py", "operation": "modify", "content": "new content\n"}]
    )
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request(expected_files=["src/existing.py"])

    res = agent.execute(req)
    assert res.status == "FAILED"
    assert res.errors[0].code == "INTEGRATION_UNAVAILABLE"
    assert "exceeds size limit" in res.errors[0].message
    assert len(gateway.requests) == 0


def test_repository_failure_is_retryable() -> None:
    """Repository failure -> FAILED/INTEGRATION_UNAVAILABLE retryable and gateway NOT called."""
    repo = TooLargeRepository()
    reply = make_valid_changeset_reply(
        changes=[{"path": "src/test.py", "operation": "create", "content": "x\n"}]
    )
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request(expected_files=["src/test.py"])

    res = agent.execute(req)
    assert res.status == "FAILED"
    assert res.errors[0].code == "INTEGRATION_UNAVAILABLE"
    assert len(gateway.requests) == 0


def test_file_not_found_from_repository_is_not_error() -> None:
    """File-not-found from repository is NOT an error (file does not exist)."""
    repo = InMemoryRepository()  # Empty repo
    reply = make_valid_changeset_reply(
        changes=[{"path": "src/new.py", "operation": "create", "content": "new content\n"}]
    )
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request(expected_files=["src/new.py"])

    res = agent.execute(req)
    # Should succeed (file doesn't exist, which is fine for create)
    assert res.status == "SUCCESS"


def test_gateway_llm_timeout_retryable() -> None:
    """Gateway LLM_TIMEOUT -> FAILED/LLM_TIMEOUT retryable."""
    agent = make_agent_with_gateway(TimeoutGateway())
    req = make_implement_request()

    res = agent.execute(req)
    assert res.status == "FAILED"
    assert res.errors[0].code == "LLM_TIMEOUT"
    assert res.errors[0].retryable is True


def test_gateway_llm_rate_limited_retryable() -> None:
    """Gateway LLM_RATE_LIMITED -> FAILED/LLM_RATE_LIMITED retryable."""
    agent = make_agent_with_gateway(RateLimitGateway())
    req = make_implement_request()

    res = agent.execute(req)
    assert res.status == "FAILED"
    assert res.errors[0].code == "LLM_RATE_LIMITED"
    assert res.errors[0].retryable is True


def test_gateway_llm_invalid_response_retryable() -> None:
    """Gateway LLM_INVALID_RESPONSE -> FAILED/LLM_INVALID_RESPONSE retryable."""
    agent = make_agent_with_gateway(ModelErrorGateway())
    req = make_implement_request()

    res = agent.execute(req)
    assert res.status == "FAILED"
    assert res.errors[0].code == "LLM_INVALID_RESPONSE"
    assert res.errors[0].retryable is True


def test_gateway_unknown_exception_retryable() -> None:
    """Unknown exception -> FAILED/AGENT_EXECUTION_FAILED retryable."""
    agent = make_agent_with_gateway(UnexpectedErrorGateway())
    req = make_implement_request()

    res = agent.execute(req)
    assert res.status == "FAILED"
    assert res.errors[0].code == "AGENT_EXECUTION_FAILED"
    assert res.errors[0].retryable is True


# Invalid reply tests
def test_invalid_reply_not_json() -> None:
    """Not valid JSON -> FAILED/LLM_INVALID_RESPONSE."""
    repo = InMemoryRepository()
    agent, gateway = make_agent_with_repo(["{not valid json}"], repo)
    req = make_implement_request()

    res = agent.execute(req)
    assert res.status == "FAILED"
    assert res.errors[0].code == "LLM_INVALID_RESPONSE"
    assert "parseError" in res.errors[0].details


def test_invalid_reply_not_object() -> None:
    """JSON not an object -> FAILED/LLM_INVALID_RESPONSE."""
    repo = InMemoryRepository()
    agent, gateway = make_agent_with_repo(["[]"], repo)
    req = make_implement_request()

    res = agent.execute(req)
    assert res.status == "FAILED"
    assert res.errors[0].code == "LLM_INVALID_RESPONSE"
    assert "parseError" in res.errors[0].details


def test_invalid_reply_extra_top_level_field() -> None:
    """Extra top-level field -> FAILED/LLM_INVALID_RESPONSE."""
    repo = InMemoryRepository()
    bad_reply = json.dumps({"changes": [], "extraKey": "not allowed"})
    agent, gateway = make_agent_with_repo([bad_reply], repo)
    req = make_implement_request()

    res = agent.execute(req)
    assert res.status == "FAILED"
    assert res.errors[0].code == "LLM_INVALID_RESPONSE"
    assert "validationError" in res.errors[0].details


def test_invalid_reply_extra_field_in_change() -> None:
    """Extra field inside a change -> FAILED/LLM_INVALID_RESPONSE."""
    repo = InMemoryRepository()
    bad_reply = json.dumps(
        {
            "changes": [
                {
                    "path": "src/test.py",
                    "operation": "create",
                    "content": "x",
                    "extra": "not allowed",
                }
            ]
        }
    )
    agent, gateway = make_agent_with_repo([bad_reply], repo)
    req = make_implement_request(expected_files=["src/test.py"])

    res = agent.execute(req)
    assert res.status == "FAILED"
    assert res.errors[0].code == "LLM_INVALID_RESPONSE"
    assert "validationError" in res.errors[0].details


def test_invalid_reply_wrong_operation() -> None:
    """Wrong operation value -> FAILED/LLM_INVALID_RESPONSE."""
    repo = InMemoryRepository()
    bad_reply = json.dumps(
        {"changes": [{"path": "src/test.py", "operation": "invalid", "content": "x"}]}
    )
    agent, gateway = make_agent_with_repo([bad_reply], repo)
    req = make_implement_request(expected_files=["src/test.py"])

    res = agent.execute(req)
    assert res.status == "FAILED"
    assert res.errors[0].code == "LLM_INVALID_RESPONSE"
    assert "validationError" in res.errors[0].details


def test_invalid_reply_missing_content_for_create() -> None:
    """Missing content for create -> FAILED/LLM_INVALID_RESPONSE."""
    repo = InMemoryRepository()
    bad_reply = json.dumps({"changes": [{"path": "src/test.py", "operation": "create"}]})
    agent, gateway = make_agent_with_repo([bad_reply], repo)
    req = make_implement_request(expected_files=["src/test.py"])

    res = agent.execute(req)
    assert res.status == "FAILED"
    assert res.errors[0].code == "LLM_INVALID_RESPONSE"
    assert "validationError" in res.errors[0].details


def test_invalid_reply_missing_content_for_modify() -> None:
    """Missing content for modify -> FAILED/LLM_INVALID_RESPONSE."""
    repo = InMemoryRepository()
    bad_reply = json.dumps({"changes": [{"path": "src/test.py", "operation": "modify"}]})
    agent, gateway = make_agent_with_repo([bad_reply], repo)
    req = make_implement_request(expected_files=["src/test.py"])

    res = agent.execute(req)
    assert res.status == "FAILED"
    assert res.errors[0].code == "LLM_INVALID_RESPONSE"
    assert "validationError" in res.errors[0].details


def test_invalid_reply_content_present_on_delete() -> None:
    """Content present on delete -> FAILED/LLM_INVALID_RESPONSE."""
    repo = InMemoryRepository()
    bad_reply = json.dumps(
        {"changes": [{"path": "src/test.py", "operation": "delete", "content": "x"}]}
    )
    agent, gateway = make_agent_with_repo([bad_reply], repo)
    req = make_implement_request(expected_files=["src/test.py"])

    res = agent.execute(req)
    assert res.status == "FAILED"
    assert res.errors[0].code == "LLM_INVALID_RESPONSE"
    assert "validationError" in res.errors[0].details


def test_invalid_reply_empty_object() -> None:
    """Empty object -> FAILED/LLM_INVALID_RESPONSE."""
    repo = InMemoryRepository()
    agent, gateway = make_agent_with_repo(["{}"], repo)
    req = make_implement_request()

    res = agent.execute(req)
    assert res.status == "FAILED"
    assert res.errors[0].code == "LLM_INVALID_RESPONSE"
    assert "validationError" in res.errors[0].details


# Semantic validation tests
def test_modify_missing_file_treated_as_create() -> None:
    """Modify on missing file -> the operation label is normalized.

    Changesets carry full file contents, so create/modify are two
    labels for one intent (set this path to this content); the label
    is aligned with the repository state instead of rejecting a reply
    whose only fault is the label.
    """
    repo = InMemoryRepository()  # Empty repo
    reply = make_valid_changeset_reply(
        changes=[{"path": "src/missing.py", "operation": "modify", "content": "new content\n"}]
    )
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request(expected_files=["src/missing.py"])

    res = agent.execute(req)
    assert res.status == "SUCCESS"
    changes = res.artifacts[0].content["changeSet"]["changes"]
    assert changes[0]["operation"] == "create"


def test_delete_missing_file_rejected() -> None:
    """Delete on missing file -> FAILED/LLM_INVALID_RESPONSE with missingPaths."""
    repo = InMemoryRepository()  # Empty repo
    reply = make_valid_changeset_reply(changes=[{"path": "src/missing.py", "operation": "delete"}])
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request(expected_files=["src/missing.py"])

    res = agent.execute(req)
    assert res.status == "FAILED"
    assert res.errors[0].code == "LLM_INVALID_RESPONSE"
    assert "missingPaths" in res.errors[0].details
    missing = res.errors[0].details["missingPaths"]
    assert any(m["path"] == "src/missing.py" and m["operation"] == "delete" for m in missing)


def test_create_existing_file_treated_as_modify() -> None:
    """Create on existing file -> the operation label is normalized.

    A local workspace folder already holds files from earlier steps
    and runs; insisting on the exact label would fail the run for a
    reply whose content is exactly what was asked for.
    """
    repo = InMemoryRepository({"main": {"src/existing.py": "old content\n"}})
    reply = make_valid_changeset_reply(
        changes=[{"path": "src/existing.py", "operation": "create", "content": "new content\n"}]
    )
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request(expected_files=["src/existing.py"])

    res = agent.execute(req)
    assert res.status == "SUCCESS"
    changes = res.artifacts[0].content["changeSet"]["changes"]
    assert changes[0]["operation"] == "modify"
