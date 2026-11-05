"""Tests for ImplementAgent output (happy paths, metadata, determinism, contract, prompt)."""

from __future__ import annotations

import copy

from asf.tools.fake import InMemoryRepository
from tests.unit.contract_models import validator_for
from tests.unit.implement_helpers import (
    make_agent_with_repo,
    make_implement_request,
    make_plan_artifact,
    make_spec_artifact,
    make_task_artifact,
    make_valid_changeset_reply,
)


def test_happy_create():
    """Happy path: create operation succeeds."""
    repo = InMemoryRepository()
    reply = make_valid_changeset_reply(
        changes=[
            {
                "path": "src/calculator.py",
                "operation": "create",
                "content": "def add(a, b):\n    return a + b\n",
            }
        ]
    )
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request(expected_files=["src/calculator.py"])

    res = agent.execute(req)
    assert res.status == "SUCCESS"
    assert len(res.artifacts) == 1
    artifact = res.artifacts[0]
    assert artifact.type == "CODE"
    assert artifact.content["format"] == "json"
    changes = artifact.content["changeSet"]["changes"]
    assert len(changes) == 1
    assert changes[0]["path"] == "src/calculator.py"
    assert changes[0]["operation"] == "create"


def test_happy_modify():
    """Happy path: modify operation succeeds."""
    repo = InMemoryRepository({"main": {"src/calculator.py": "def add(a, b):\n    return a + b\n"}})
    reply = make_valid_changeset_reply(
        changes=[
            {
                "path": "src/calculator.py",
                "operation": "modify",
                "content": (
                    "def add(a, b):\n    return a + b\n\n"
                    "def subtract(a, b):\n    return a - b\n"
                ),
            }
        ]
    )
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request(expected_files=["src/calculator.py"])

    res = agent.execute(req)
    assert res.status == "SUCCESS"
    artifact = res.artifacts[0]
    changes = artifact.content["changeSet"]["changes"]
    assert changes[0]["operation"] == "modify"


def test_happy_delete():
    """Happy path: delete operation succeeds."""
    repo = InMemoryRepository({"main": {"src/old.py": "old content\n"}})
    reply = make_valid_changeset_reply(
        changes=[{"path": "src/old.py", "operation": "delete"}]
    )
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request(expected_files=["src/old.py"])

    res = agent.execute(req)
    assert res.status == "SUCCESS"
    artifact = res.artifacts[0]
    changes = artifact.content["changeSet"]["changes"]
    assert changes[0]["operation"] == "delete"
    assert "content" not in changes[0] or changes[0].get("content") is None


def test_happy_mixed_change_set():
    """Happy path: mixed change set (create, modify, delete)."""
    repo = InMemoryRepository(
        {"main": {"src/existing.py": "old content\n", "src/to_delete.py": "delete me\n"}}
    )
    reply = make_valid_changeset_reply(
        changes=[
            {"path": "src/new.py", "operation": "create", "content": "new file\n"},
            {"path": "src/existing.py", "operation": "modify", "content": "modified content\n"},
            {"path": "src/to_delete.py", "operation": "delete"},
        ]
    )
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request(
        expected_files=["src/new.py", "src/existing.py", "src/to_delete.py"]
    )

    res = agent.execute(req)
    assert res.status == "SUCCESS"
    artifact = res.artifacts[0]
    changes = artifact.content["changeSet"]["changes"]
    assert len(changes) == 3
    ops = [c["operation"] for c in changes]
    assert "create" in ops
    assert "modify" in ops
    assert "delete" in ops


def test_full_metadata_injected():
    """Full metadata set injected from inputs."""
    repo = InMemoryRepository()
    reply = make_valid_changeset_reply()
    agent, gateway = make_agent_with_repo([reply], repo)
    spec_art = make_spec_artifact(artifact_id="spec-123", version="2")
    plan_art = make_plan_artifact(artifact_id="plan-456", version="3")
    task_art = make_task_artifact(artifact_id="task-789", version="4")
    req = make_implement_request(
        spec_artifact=spec_art,
        plan_artifact=plan_art,
        task_artifact=task_art,
        task_item_id="T5",
        ref="main",
    )

    res = agent.execute(req)
    assert res.status == "SUCCESS"
    artifact = res.artifacts[0]
    meta = artifact.metadata
    assert meta["specArtifactId"] == "spec-123"
    assert meta["specVersion"] == "2"
    assert meta["planArtifactId"] == "plan-456"
    assert meta["planVersion"] == "3"
    assert meta["taskItemId"] == "T5"
    assert meta["taskArtifactId"] == "task-789"
    assert meta["taskVersion"] == "4"
    assert meta["baseRef"] == "main"
    assert "generatedAt" in meta
    assert "artifactKind" in meta
    assert meta["artifactKind"] == "CODE"


def test_llm_reply_metadata_cannot_override():
    """LLM reply containing metadata fields cannot override them."""
    repo = InMemoryRepository()
    reply = make_valid_changeset_reply(
        changes=[{"path": "src/calculator.py", "operation": "create", "content": "x\n"}]
    )
    agent, gateway = make_agent_with_repo([reply], repo)
    spec_art = make_spec_artifact(artifact_id="spec-real", version="1")
    plan_art = make_plan_artifact(artifact_id="plan-real", version="1")
    task_art = make_task_artifact(artifact_id="task-real", version="1")
    req = make_implement_request(
        spec_artifact=spec_art,
        plan_artifact=plan_art,
        task_artifact=task_art,
    )

    res = agent.execute(req)
    assert res.status == "SUCCESS"
    artifact = res.artifacts[0]
    meta = artifact.metadata
    assert meta["specArtifactId"] == "spec-real"
    assert meta["planArtifactId"] == "plan-real"
    assert meta["taskArtifactId"] == "task-real"
    assert meta["taskItemId"] == "T1"


def test_rendered_text_deterministic():
    """Rendered text is deterministic (same input -> same text)."""
    reply = make_valid_changeset_reply(
        changes=[
            {
                "path": "src/calculator.py",
                "operation": "create",
                "content": "def add(a, b):\n    return a + b\n",
            }
        ]
    )
    agent1, _ = make_agent_with_repo([reply], InMemoryRepository())
    agent2, _ = make_agent_with_repo([reply], InMemoryRepository())
    req = make_implement_request()

    res1 = agent1.execute(req)
    req2 = copy.deepcopy(req)
    res2 = agent2.execute(req2)

    assert res1.status == "SUCCESS"
    assert res2.status == "SUCCESS"
    assert res1.artifacts[0].content["text"] == res2.artifacts[0].content["text"]
    assert res1.artifacts[0].content["changeSet"] == res2.artifacts[0].content["changeSet"]


def test_artifact_validates_against_contract():
    """Output artifact validates against the contract schema."""
    repo = InMemoryRepository()
    reply = make_valid_changeset_reply()
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request()

    res = agent.execute(req)
    assert res.status == "SUCCESS"
    artifact = res.artifacts[0]
    validator_for("Artifact").validate(artifact.to_contract())
    validator_for("AgentResult").validate(res.to_contract())


def test_prompt_contains_spec_section():
    """Captured gateway request contains SPEC section with delimiters."""
    repo = InMemoryRepository()
    reply = make_valid_changeset_reply()
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request()

    res = agent.execute(req)
    assert res.status == "SUCCESS"
    assert len(gateway.requests) == 1
    messages = gateway.requests[0].messages
    user_content = "\n".join(m.content for m in messages if m.role == "user")
    assert "<<<SPEC>>>" in user_content
    assert "<<<END SPEC>>>" in user_content


def test_prompt_contains_plan_section():
    """Captured gateway request contains PLAN section with delimiters."""
    repo = InMemoryRepository()
    reply = make_valid_changeset_reply()
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request()

    res = agent.execute(req)
    assert res.status == "SUCCESS"
    messages = gateway.requests[0].messages
    user_content = "\n".join(m.content for m in messages if m.role == "user")
    assert "<<<PLAN>>>" in user_content
    assert "<<<END PLAN>>>" in user_content


def test_prompt_contains_task_item_section():
    """Captured gateway request contains TASK ITEM section with delimiters."""
    repo = InMemoryRepository()
    reply = make_valid_changeset_reply()
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request()

    res = agent.execute(req)
    assert res.status == "SUCCESS"
    messages = gateway.requests[0].messages
    user_content = "\n".join(m.content for m in messages if m.role == "user")
    assert "<<<TASK ITEM>>>" in user_content
    assert "<<<END TASK ITEM>>>" in user_content


def test_prompt_contains_existing_files_section():
    """Captured gateway request contains existing files section with delimiters."""
    repo = InMemoryRepository({"main": {"src/existing.py": "old content\n"}})
    reply = make_valid_changeset_reply(
        changes=[{"path": "src/existing.py", "operation": "modify", "content": "new content\n"}]
    )
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request(expected_files=["src/existing.py"])

    res = agent.execute(req)
    assert res.status == "SUCCESS"
    messages = gateway.requests[0].messages
    user_content = "\n".join(m.content for m in messages if m.role == "user")
    assert "<<<FILE: src/existing.py>>>" in user_content
    assert "old content" in user_content
    assert "<<<END FILE: src/existing.py>>>" in user_content


def test_prompt_no_existing_files_when_none():
    """Prompt has no existing files section when no files exist."""
    repo = InMemoryRepository()
    reply = make_valid_changeset_reply()
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request()

    res = agent.execute(req)
    assert res.status == "SUCCESS"
    messages = gateway.requests[0].messages
    user_content = "\n".join(m.content for m in messages if m.role == "user")
    assert "<<<FILE:" not in user_content


def test_prompt_contains_json_schema():
    """Captured gateway request contains JSON schema for ChangeSet."""
    repo = InMemoryRepository()
    reply = make_valid_changeset_reply()
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request()

    res = agent.execute(req)
    assert res.status == "SUCCESS"
    messages = gateway.requests[0].messages
    user_content = "\n".join(m.content for m in messages if m.role == "user")
    assert '"changes"' in user_content
    assert '"operation"' in user_content
    assert '"content"' in user_content


def test_prompt_contains_rules():
    """Captured gateway request contains implementation rules."""
    repo = InMemoryRepository()
    reply = make_valid_changeset_reply()
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request()

    res = agent.execute(req)
    assert res.status == "SUCCESS"
    messages = gateway.requests[0].messages
    user_content = "\n".join(m.content for m in messages if m.role == "user")
    assert "Full file contents only" in user_content
    assert "No diffs" in user_content
    assert "No NUL bytes" in user_content
    assert "valid UTF-8" in user_content
    assert "No secrets" in user_content


def test_prompt_system_message_present():
    """System message is included in prompt."""
    repo = InMemoryRepository()
    reply = make_valid_changeset_reply()
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request()

    res = agent.execute(req)
    assert res.status == "SUCCESS"
    messages = gateway.requests[0].messages
    # Stable -> changing message order: system, the SPEC/PLAN
    # reference message, then the per-item message (the prompt
    # caching layout).
    assert len(messages) == 3
    assert messages[0].role == "system"
    assert messages[1].role == "user"
    assert messages[2].role == "user"
    assert "<<<SPEC>>>" in messages[1].content
    assert len(messages[0].content) > 0


def test_output_artifact_format_json():
    """Output artifact has format=json."""
    repo = InMemoryRepository()
    reply = make_valid_changeset_reply()
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request()

    res = agent.execute(req)
    assert res.status == "SUCCESS"
    artifact = res.artifacts[0]
    assert artifact.content.get("format") == "json"
    assert "changeSet" in artifact.content
    assert "text" in artifact.content


def test_output_artifact_content_structure():
    """Output artifact content structure is correct."""
    repo = InMemoryRepository()
    reply = make_valid_changeset_reply(
        changes=[{"path": "src/test.py", "operation": "create", "content": "print('hello')\n"}]
    )
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request(expected_files=["src/test.py"])

    res = agent.execute(req)
    assert res.status == "SUCCESS"
    artifact = res.artifacts[0]
    changeset = artifact.content["changeSet"]
    assert changeset["changes"][0]["path"] == "src/test.py"
    assert changeset["changes"][0]["operation"] == "create"
    assert changeset["changes"][0]["content"] == "print('hello')\n"


def test_output_artifact_text_is_markdown():
    """Output artifact text is markdown with file content."""
    repo = InMemoryRepository()
    reply = make_valid_changeset_reply(
        changes=[{"path": "src/test.py", "operation": "create", "content": "print('hello')\n"}]
    )
    agent, gateway = make_agent_with_repo([reply], repo)
    req = make_implement_request(expected_files=["src/test.py"])

    res = agent.execute(req)
    assert res.status == "SUCCESS"
    artifact = res.artifacts[0]
    text = artifact.content["text"]
    assert "# CODE: Implementation" in text
    assert "src/test.py" in text
    assert "print('hello')" in text
    assert "```python" in text


def test_reply_wrapped_in_code_fence_accepted():
    """Reply wrapped in a code fence is accepted."""
    repo = InMemoryRepository()
    fence_reply = "```json\n" + make_valid_changeset_reply() + "\n```"
    agent, gateway = make_agent_with_repo([fence_reply], repo)
    req = make_implement_request()

    res = agent.execute(req)
    assert res.status == "SUCCESS"