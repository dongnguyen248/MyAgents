"""Edit blocks, finish-reason handling, and the repair loop.

Covers the mandatory scenarios: truncated replies fail with
LLM_OUTPUT_TRUNCATED and are never parsed; SEARCH matching 0/1/2
times; several blocks on one file; CRLF preservation; a repair
that succeeds on the second call with summed usage; no repair on
truncation or secrets; the legacy JSON format behind its flag;
and the token-size win on a 3-line change in a 1000-line file.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from asf.agents._shared.model_call import classify_finish_reason
from asf.agents.base import AgentRuntime
from asf.agents.fix.agent import FixAgent
from asf.agents.fix.prompts import FixPrompts
from asf.agents.implement.agent import ImplementAgent
from asf.agents.loading import load_implement_prompts
from asf.contracts.models import (
    AgentRequest,
    Artifact,
    ModelResponse,
    ModelUsage,
)
from asf.models.fake import ScriptedModelGateway
from asf.tools.edit_blocks import EditBlockError, parse_edit_blocks
from asf.tools.fake import InMemoryRepository
from tests.unit.implement_helpers import counter_id, make_implement_request

T_AWARE = datetime(2026, 11, 5, 17, 0, tzinfo=timezone.utc)
CALC = "def add(a, b):\n    return a + b\n\n\ndef subtract(a, b):\n    return a - b\n"


# -- finish reasons -----------------------------------------------------------


def test_finish_reason_classification():
    assert classify_finish_reason("length") == "truncated"
    assert classify_finish_reason("MAX_TOKENS") == "truncated"
    assert classify_finish_reason("stop") == "ok"
    assert classify_finish_reason("STOP") == "ok"
    assert classify_finish_reason("content_filter") == "blocked"
    assert classify_finish_reason("SAFETY") == "blocked"


# -- the parser -----------------------------------------------------------------


def test_search_must_match_exactly_once():
    existing = {"src/calculator.py": CALC}
    zero = (
        "FILE: src/calculator.py\n<<<<<<< SEARCH\nnot in the file\n"
        "=======\nx\n>>>>>>> REPLACE\n"
    )
    with pytest.raises(EditBlockError) as caught:
        parse_edit_blocks(zero, existing_files=existing)
    assert "matched 0 times" in str(caught.value)
    assert "src/calculator.py" in str(caught.value)

    with pytest.raises(EditBlockError) as caught:
        parse_edit_blocks(
            "FILE: f.py\n<<<<<<< SEARCH\n= a\n=======\n= b\n>>>>>>> REPLACE\n",
            existing_files={"f.py": "x = a\ny = a\n"},
        )
    assert "matched 2 times" in str(caught.value)
    assert "f.py" in str(caught.value)


def test_multiple_blocks_on_one_file_apply_in_order():
    reply = (
        "FILE: src/calculator.py\n"
        "<<<<<<< SEARCH\n    return a + b\n=======\n    return a + b  # sum\n>>>>>>> REPLACE\n"
        "<<<<<<< SEARCH\n    return a - b\n=======\n    return a - b  # diff\n>>>>>>> REPLACE\n"
    )
    changeset = parse_edit_blocks(reply, existing_files={"src/calculator.py": CALC})
    assert len(changeset.changes) == 1
    change = changeset.changes[0]
    assert change.operation == "modify"
    assert change.content is not None
    assert "return a + b  # sum" in change.content
    assert "return a - b  # diff" in change.content


def test_crlf_line_endings_are_preserved():
    crlf = CALC.replace("\n", "\r\n")
    reply = (
        "FILE: src/calculator.py\n"
        "<<<<<<< SEARCH\n    return a + b\n=======\n    return a + b  # sum\n>>>>>>> REPLACE\n"
    )
    changeset = parse_edit_blocks(reply, existing_files={"src/calculator.py": crlf})
    content = changeset.changes[0].content
    assert content is not None
    assert content == crlf.replace("return a + b", "return a + b  # sum")
    assert "\n" not in content.replace("\r\n", "")


def test_create_delete_and_scope_rules():
    reply = (
        "CREATE: src/util.py\n<<<<<<< FILE\ndef help():\n    return 1\n>>>>>>> FILE\n\n"
        "DELETE: src/old.py\n"
    )
    changeset = parse_edit_blocks(
        reply,
        existing_files={"src/old.py": "x = 1\n"},
        expected_files=["src/util.py", "src/old.py"],
    )
    by_path = {change.path: change for change in changeset.changes}
    assert by_path["src/util.py"].operation == "create"
    assert by_path["src/util.py"].content == "def help():\n    return 1\n"
    assert by_path["src/old.py"].operation == "delete"

    with pytest.raises(EditBlockError, match="not in the expected files"):
        parse_edit_blocks(
            "DELETE: src/other.py\n",
            existing_files={}, expected_files=["src/util.py"],
        )
    with pytest.raises(EditBlockError, match="already exists"):
        parse_edit_blocks(
            "CREATE: src/util.py\n<<<<<<< FILE\nx\n>>>>>>> FILE\n",
            existing_files={"src/util.py": "y\n"},
        )
    with pytest.raises(EditBlockError, match="does not exist"):
        parse_edit_blocks(
            "FILE: src/missing.py\n<<<<<<< SEARCH\nx\n=======\ny\n>>>>>>> REPLACE\n",
            existing_files={},
        )
    with pytest.raises(EditBlockError, match="Unexpected line"):
        parse_edit_blocks(
            "Here is your change:\nDELETE: src/old.py\n",
            existing_files={"src/old.py": "x\n"},
        )


# -- the implement agent ----------------------------------------------------------


def _implement_agent(script, repo: InMemoryRepository, **kwargs):
    gateway = ScriptedModelGateway(script)
    runtime = AgentRuntime(
        models=gateway, clock=lambda: T_AWARE, new_id=counter_id("gen-"),
    )
    agent = ImplementAgent(
        runtime, repo, prompts=load_implement_prompts(), **kwargs,
    )
    return agent, gateway


def _repo_with_calc() -> InMemoryRepository:
    return InMemoryRepository({"main": {"src/calculator.py": CALC}})


GOOD_BLOCKS = (
    "FILE: src/calculator.py\n"
    "<<<<<<< SEARCH\n    return a + b\n=======\n    return a + b  # sum\n>>>>>>> REPLACE\n"
)


def _response(content: str, *, finish: str = "stop", usage=(10, 5)) -> ModelResponse:
    return ModelResponse(
        content=content, model="test-model",
        usage=ModelUsage(prompt_tokens=usage[0], completion_tokens=usage[1]),
        finish_reason=finish,
    )


def test_truncated_reply_fails_with_the_truncation_code_and_no_repair():
    agent, gateway = _implement_agent(
        [_response('{"changes": [{"path": "src/cal', finish="length")],
        _repo_with_calc(),
    )
    result = agent.execute(make_implement_request())
    assert result.status == "FAILED"
    assert result.errors[0].code == "LLM_OUTPUT_TRUNCATED"
    assert result.errors[0].retryable is True
    assert len(gateway.requests) == 1  # never parsed, never repaired


def test_repair_succeeds_on_the_second_call_and_sums_usage():
    bad = (
        "FILE: src/calculator.py\n"
        "<<<<<<< SEARCH\n    return a * b\n=======\n    return 0\n>>>>>>> REPLACE\n"
    )
    agent, gateway = _implement_agent(
        [_response(bad, usage=(10, 5)), _response(GOOD_BLOCKS, usage=(20, 7))],
        _repo_with_calc(),
    )
    result = agent.execute(make_implement_request())
    assert result.status == "SUCCESS"
    assert result.output["repairs"] == 1
    assert result.output["usage"] == {"promptTokens": 30, "completionTokens": 12}
    assert len(gateway.requests) == 2
    repair_messages = gateway.requests[1].messages
    assert [m.role for m in repair_messages] == ["system", "user", "assistant", "user"]
    assert "matched 0 times" in repair_messages[-1].content
    assert repair_messages[2].content == bad[:8000]


def test_secret_in_scope_is_not_repaired():
    secret_blocks = (
        "FILE: src/calculator.py\n"
        "<<<<<<< SEARCH\n    return a + b\n=======\n"
        "    return 'AKIAIOSFODNN7EXAMPLE'\n>>>>>>> REPLACE\n"
    )
    agent, gateway = _implement_agent(
        [_response(secret_blocks)], _repo_with_calc(),
    )
    result = agent.execute(make_implement_request())
    assert result.status == "FAILED"
    assert "secret" in result.errors[0].message.lower()
    assert len(gateway.requests) == 1


def test_json_format_still_works_behind_the_flag():
    reply = json.dumps({"changes": [{
        "path": "src/calculator.py", "operation": "modify",
        "content": CALC.replace("a + b", "a + b  # sum"),
    }]})
    agent, gateway = _implement_agent(
        [_response(reply)], _repo_with_calc(), edit_format="json",
    )
    result = agent.execute(make_implement_request())
    assert result.status == "SUCCESS"
    assert result.output["repairs"] == 0


def test_blocks_are_the_default_and_the_prompt_says_so():
    agent, gateway = _implement_agent([_response(GOOD_BLOCKS)], _repo_with_calc())
    result = agent.execute(make_implement_request())
    assert result.status == "SUCCESS"
    user = gateway.requests[0].messages[-1].content
    assert "SEARCH" in user and "Full file contents only" not in user


# -- the fix agent -----------------------------------------------------------------


def _fix_request() -> AgentRequest:
    base = make_implement_request(
        expected_files=["src/calculator.py", "src/util.py"],
    )
    code = Artifact(
        id="code-1", type="CODE", name="CODE.json", version="1",
        content={
            "format": "json",
            "changeSet": {"changes": [
                {"path": "src/calculator.py", "operation": "create", "content": CALC},
                {"path": "src/util.py", "operation": "create",
                 "content": "def help():\n    return 1\n"},
            ]},
            "text": "code",
        },
        created_by="agent-implement", created_at=T_AWARE,
        metadata={
            "baseRef": "main", "taskItemId": "T1",
            "specArtifactId": "spec-1", "specVersion": "1",
            "planArtifactId": "plan-1", "planVersion": "1",
            "taskArtifactId": "task-1", "taskVersion": "1",
        },
    )
    review = Artifact(
        id="review-1", type="CODE_REVIEW", name="CODE_REVIEW.md", version="1",
        content={
            "format": "json",
            "review": {"findings": [], "verdict": "CHANGES_REQUESTED"},
            "text": "# Review\nVerdict: CHANGES_REQUESTED",
        },
        created_by="agent-review", created_at=T_AWARE,
        metadata={"codeArtifactId": "code-1", "codeVersion": "1", "taskItemId": "T1"},
    )
    return base.model_copy(update={
        "agent_id": "agent-fix",
        "artifacts": [*base.artifacts, code, review],
    })


def _fix_agent(script, **kwargs):
    gateway = ScriptedModelGateway(script)
    runtime = AgentRuntime(
        models=gateway, clock=lambda: T_AWARE, new_id=counter_id("fix-"),
    )
    agent = FixAgent(
        runtime, InMemoryRepository({"main": {}}),
        prompts=FixPrompts("You fix one task item's CODE"), **kwargs,
    )
    return agent, gateway


def test_fix_blocks_preserve_untouched_previous_changes():
    reply = (
        "FILE: src/calculator.py\n"
        "<<<<<<< SEARCH\n    return a - b\n=======\n    return a - b  # diff\n>>>>>>> REPLACE\n"
    )
    agent, _gateway = _fix_agent([_response(reply)])
    result = agent.execute(_fix_request())
    assert result.status == "SUCCESS"
    changeset = result.artifacts[0].content["changeSet"]
    by_path = {change["path"]: change for change in changeset["changes"]}
    # The touched file carries the fix; the untouched previous
    # change (util.py) is preserved in the replacement.
    assert "return a - b  # diff" in by_path["src/calculator.py"]["content"]
    assert by_path["src/util.py"]["content"] == "def help():\n    return 1\n"
    assert result.output["repairs"] == 0


def test_fix_repair_loop_and_truncation():
    bad = (
        "FILE: src/calculator.py\n"
        "<<<<<<< SEARCH\nnope\n=======\nx\n>>>>>>> REPLACE\n"
    )
    good = (
        "FILE: src/calculator.py\n"
        "<<<<<<< SEARCH\n    return a - b\n=======\n    return a - b  # diff\n>>>>>>> REPLACE\n"
    )
    agent, gateway = _fix_agent([
        _response(bad, usage=(3, 2)), _response(good, usage=(4, 3)),
    ])
    result = agent.execute(_fix_request())
    assert result.status == "SUCCESS"
    assert result.output["repairs"] == 1
    assert result.output["usage"] == {"promptTokens": 7, "completionTokens": 5}

    agent2, gateway2 = _fix_agent([_response(good, finish="MAX_TOKENS")])
    result2 = agent2.execute(_fix_request())
    assert result2.status == "FAILED"
    assert result2.errors[0].code == "LLM_OUTPUT_TRUNCATED"
    assert len(gateway2.requests) == 1


# -- the size win ---------------------------------------------------------------------


def test_blocks_completion_is_far_smaller_than_full_file_json():
    lines = [f"def fn_{i}(x):\n    return x + {i}" for i in range(500)]
    big_file = "\n\n".join(lines) + "\n"
    assert big_file.count("\n") >= 1000
    changed = big_file.replace("return x + 250", "return x + 250  # patched")
    json_reply = json.dumps({"changes": [{
        "path": "src/big.py", "operation": "modify", "content": changed,
    }]})
    blocks_reply = (
        "FILE: src/big.py\n<<<<<<< SEARCH\ndef fn_250(x):\n    return x + 250\n"
        "=======\ndef fn_250(x):\n    return x + 250  # patched\n>>>>>>> REPLACE\n"
    )
    changeset = parse_edit_blocks(blocks_reply, existing_files={"src/big.py": big_file})
    assert changeset.changes[0].content == changed
    assert len(blocks_reply) * 4 < len(json_reply)
