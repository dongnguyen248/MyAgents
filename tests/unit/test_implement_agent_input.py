"""Tests for ImplementAgent input validation (_check method)."""

from __future__ import annotations

from asf.contracts.models import AgentRequest, Artifact
from tests.unit.implement_helpers import (
    T_AWARE,
    make_agent_and_gateway,
    make_implement_request,
    make_plan_artifact,
    make_spec_artifact,
    make_task_artifact,
    make_valid_changeset_reply,
)


def test_validate_missing_spec_artifact() -> None:
    """Missing SPEC artifact -> REJECTED/VALIDATION_FAILED."""
    agent, gateway = make_agent_and_gateway([])
    valid_plan = make_plan_artifact()
    valid_task = make_task_artifact()
    req = AgentRequest(
        request_id="req-1",
        task_id="task-1",
        project_id="proj-1",
        workflow_id="software-development",
        agent_id="agent-implement",
        input={"taskItemId": "T1", "ref": "main"},
        context={"project": {}},
        artifacts=[valid_plan, valid_task],
        metadata={"attempt": 1},
    )
    val_res = agent.validate(req)
    assert not val_res.valid
    paths = [err.details.get("path") for err in val_res.errors]
    assert "artifacts" in paths
    exec_res = agent.execute(req)
    assert exec_res.status == "REJECTED"
    assert len(gateway.requests) == 0


def test_validate_missing_plan_artifact() -> None:
    """Missing PLAN artifact -> REJECTED/VALIDATION_FAILED."""
    agent, gateway = make_agent_and_gateway([])
    valid_spec = make_spec_artifact()
    valid_task = make_task_artifact()
    req = AgentRequest(
        request_id="req-2",
        task_id="task-2",
        project_id="proj-2",
        workflow_id="software-development",
        agent_id="agent-implement",
        input={"taskItemId": "T1", "ref": "main"},
        context={"project": {}},
        artifacts=[valid_spec, valid_task],
        metadata={"attempt": 1},
    )
    val_res = agent.validate(req)
    assert not val_res.valid
    paths = [err.details.get("path") for err in val_res.errors]
    assert "artifacts" in paths
    exec_res = agent.execute(req)
    assert exec_res.status == "REJECTED"
    assert len(gateway.requests) == 0


def test_validate_missing_task_artifact() -> None:
    """Missing TASK artifact -> REJECTED/VALIDATION_FAILED."""
    agent, gateway = make_agent_and_gateway([])
    valid_spec = make_spec_artifact()
    valid_plan = make_plan_artifact()
    req = AgentRequest(
        request_id="req-3",
        task_id="task-3",
        project_id="proj-3",
        workflow_id="software-development",
        agent_id="agent-implement",
        input={"taskItemId": "T1", "ref": "main"},
        context={"project": {}},
        artifacts=[valid_spec, valid_plan],
        metadata={"attempt": 1},
    )
    val_res = agent.validate(req)
    assert not val_res.valid
    paths = [err.details.get("path") for err in val_res.errors]
    assert "artifacts" in paths
    exec_res = agent.execute(req)
    assert exec_res.status == "REJECTED"
    assert len(gateway.requests) == 0


def test_validate_duplicate_spec_artifact() -> None:
    """Duplicate SPEC artifact -> REJECTED/VALIDATION_FAILED."""
    agent, gateway = make_agent_and_gateway([])
    valid_spec = make_spec_artifact()
    valid_plan = make_plan_artifact()
    valid_task = make_task_artifact()
    req = AgentRequest(
        request_id="req-4",
        task_id="task-4",
        project_id="proj-4",
        workflow_id="software-development",
        agent_id="agent-implement",
        input={"taskItemId": "T1", "ref": "main"},
        context={"project": {}},
        artifacts=[valid_spec, valid_spec, valid_plan, valid_task],
        metadata={"attempt": 1},
    )
    val_res = agent.validate(req)
    assert not val_res.valid
    paths = [err.details.get("path") for err in val_res.errors]
    assert "artifacts" in paths
    exec_res = agent.execute(req)
    assert exec_res.status == "REJECTED"
    assert len(gateway.requests) == 0


def test_validate_duplicate_plan_artifact() -> None:
    """Duplicate PLAN artifact -> REJECTED/VALIDATION_FAILED."""
    agent, gateway = make_agent_and_gateway([])
    valid_spec = make_spec_artifact()
    valid_plan = make_plan_artifact()
    valid_task = make_task_artifact()
    req = AgentRequest(
        request_id="req-5",
        task_id="task-5",
        project_id="proj-5",
        workflow_id="software-development",
        agent_id="agent-implement",
        input={"taskItemId": "T1", "ref": "main"},
        context={"project": {}},
        artifacts=[valid_spec, valid_plan, valid_plan, valid_task],
        metadata={"attempt": 1},
    )
    val_res = agent.validate(req)
    assert not val_res.valid
    paths = [err.details.get("path") for err in val_res.errors]
    assert "artifacts" in paths
    exec_res = agent.execute(req)
    assert exec_res.status == "REJECTED"
    assert len(gateway.requests) == 0


def test_validate_duplicate_task_artifact() -> None:
    """Duplicate TASK artifact -> REJECTED/VALIDATION_FAILED."""
    agent, gateway = make_agent_and_gateway([])
    valid_spec = make_spec_artifact()
    valid_plan = make_plan_artifact()
    valid_task = make_task_artifact()
    req = AgentRequest(
        request_id="req-6",
        task_id="task-6",
        project_id="proj-6",
        workflow_id="software-development",
        agent_id="agent-implement",
        input={"taskItemId": "T1", "ref": "main"},
        context={"project": {}},
        artifacts=[valid_spec, valid_plan, valid_task, valid_task],
        metadata={"attempt": 1},
    )
    val_res = agent.validate(req)
    assert not val_res.valid
    paths = [err.details.get("path") for err in val_res.errors]
    assert "artifacts" in paths
    exec_res = agent.execute(req)
    assert exec_res.status == "REJECTED"
    assert len(gateway.requests) == 0


def test_validate_code_artifact_present() -> None:
    """CODE artifact present -> REJECTED/VALIDATION_FAILED (no revision mode)."""
    agent, gateway = make_agent_and_gateway([])
    valid_spec = make_spec_artifact()
    valid_plan = make_plan_artifact()
    valid_task = make_task_artifact()
    code_art = Artifact(
        id="code-1",
        type="CODE",
        name="CODE.json",
        version="1",
        content={"format": "json", "changeSet": {"changes": []}, "text": ""},
        created_by="agent-implement",
        created_at=T_AWARE,
    )
    req = AgentRequest(
        request_id="req-7",
        task_id="task-7",
        project_id="proj-7",
        workflow_id="software-development",
        agent_id="agent-implement",
        input={"taskItemId": "T1", "ref": "main"},
        context={"project": {}},
        artifacts=[valid_spec, valid_plan, valid_task, code_art],
        metadata={"attempt": 1},
    )
    val_res = agent.validate(req)
    assert not val_res.valid
    paths = [err.details.get("path") for err in val_res.errors]
    assert "artifacts" in paths
    exec_res = agent.execute(req)
    assert exec_res.status == "REJECTED"
    assert len(gateway.requests) == 0


def test_validate_unknown_task_item_id() -> None:
    """Unknown taskItemId in TASK -> FAILED/LLM_INVALID_RESPONSE (validated in _run)."""
    agent, gateway = make_agent_and_gateway([make_valid_changeset_reply()])
    valid_spec = make_spec_artifact()
    valid_plan = make_plan_artifact()
    valid_task = make_task_artifact()
    req = make_implement_request(
        spec_artifact=valid_spec,
        plan_artifact=valid_plan,
        task_artifact=valid_task,
        task_item_id="T999",
    )
    # validate() only runs _check, which no longer validates taskItemId existence
    val_res = agent.validate(req)
    assert val_res.valid  # passes _check
    exec_res = agent.execute(req)
    assert exec_res.status == "FAILED"
    assert exec_res.errors[0].code == "LLM_INVALID_RESPONSE"
    assert "not found in TASK artifact" in exec_res.errors[0].message
    assert len(gateway.requests) == 0  # LLM not called (validation fails first)


def test_validate_malformed_task_item_id() -> None:
    """Malformed taskItemId (not matching ^T[1-9][0-9]*$) -> REJECTED/VALIDATION_FAILED."""
    agent, gateway = make_agent_and_gateway([])
    valid_spec = make_spec_artifact()
    valid_plan = make_plan_artifact()
    valid_task = make_task_artifact()
    req = make_implement_request(
        spec_artifact=valid_spec,
        plan_artifact=valid_plan,
        task_artifact=valid_task,
        task_item_id="X1",
    )
    val_res = agent.validate(req)
    assert not val_res.valid
    paths = [err.details.get("path") for err in val_res.errors]
    assert "input.taskItemId" in paths
    exec_res = agent.execute(req)
    assert exec_res.status == "REJECTED"
    assert len(gateway.requests) == 0


def test_validate_blank_task_item_id() -> None:
    """Blank taskItemId -> REJECTED/VALIDATION_FAILED."""
    agent, gateway = make_agent_and_gateway([])
    valid_spec = make_spec_artifact()
    valid_plan = make_plan_artifact()
    valid_task = make_task_artifact()
    req = make_implement_request(
        spec_artifact=valid_spec,
        plan_artifact=valid_plan,
        task_artifact=valid_task,
        task_item_id="",
    )
    val_res = agent.validate(req)
    assert not val_res.valid
    paths = [err.details.get("path") for err in val_res.errors]
    assert "input.taskItemId" in paths
    exec_res = agent.execute(req)
    assert exec_res.status == "REJECTED"
    assert len(gateway.requests) == 0


def test_validate_blank_ref() -> None:
    """Blank ref -> REJECTED/VALIDATION_FAILED."""
    agent, gateway = make_agent_and_gateway([])
    valid_spec = make_spec_artifact()
    valid_plan = make_plan_artifact()
    valid_task = make_task_artifact()
    req = make_implement_request(
        spec_artifact=valid_spec,
        plan_artifact=valid_plan,
        task_artifact=valid_task,
        ref="",
    )
    val_res = agent.validate(req)
    assert not val_res.valid
    paths = [err.details.get("path") for err in val_res.errors]
    assert "input.ref" in paths
    exec_res = agent.execute(req)
    assert exec_res.status == "REJECTED"
    assert len(gateway.requests) == 0


def test_validate_missing_ref() -> None:
    """Missing ref -> REJECTED/VALIDATION_FAILED."""
    agent, gateway = make_agent_and_gateway([])
    valid_spec = make_spec_artifact()
    valid_plan = make_plan_artifact()
    valid_task = make_task_artifact()
    req = AgentRequest(
        request_id="req-11",
        task_id="task-11",
        project_id="proj-11",
        workflow_id="software-development",
        agent_id="agent-implement",
        input={"taskItemId": "T1"},
        context={"project": {}},
        artifacts=[valid_spec, valid_plan, valid_task],
        metadata={"attempt": 1},
    )
    val_res = agent.validate(req)
    assert not val_res.valid
    paths = [err.details.get("path") for err in val_res.errors]
    assert "input.ref" in paths
    exec_res = agent.execute(req)
    assert exec_res.status == "REJECTED"
    assert len(gateway.requests) == 0


def test_validate_wrong_agent_id() -> None:
    """Wrong agentId -> REJECTED/VALIDATION_FAILED."""
    agent, gateway = make_agent_and_gateway([])
    valid_spec = make_spec_artifact()
    valid_plan = make_plan_artifact()
    valid_task = make_task_artifact()
    req = make_implement_request(
        spec_artifact=valid_spec,
        plan_artifact=valid_plan,
        task_artifact=valid_task,
        agent_id="other-agent",
    )
    val_res = agent.validate(req)
    assert not val_res.valid
    paths = [err.details.get("path") for err in val_res.errors]
    assert "agentId" in paths
    exec_res = agent.execute(req)
    assert exec_res.status == "REJECTED"
    assert len(gateway.requests) == 0


def test_validate_disallowed_input_key() -> None:
    """Disallowed input key -> REJECTED/VALIDATION_FAILED."""
    agent, gateway = make_agent_and_gateway([])
    valid_spec = make_spec_artifact()
    valid_plan = make_plan_artifact()
    valid_task = make_task_artifact()
    req = make_implement_request(
        spec_artifact=valid_spec,
        plan_artifact=valid_plan,
        task_artifact=valid_task,
    )
    req.input["extraKey"] = "not allowed"
    val_res = agent.validate(req)
    assert not val_res.valid
    paths = [err.details.get("path") for err in val_res.errors]
    assert "input.extraKey" in paths
    exec_res = agent.execute(req)
    assert exec_res.status == "REJECTED"
    assert len(gateway.requests) == 0


def test_validate_bad_language_empty_string() -> None:
    """Empty language string -> REJECTED/VALIDATION_FAILED."""
    agent, gateway = make_agent_and_gateway([])
    valid_spec = make_spec_artifact()
    valid_plan = make_plan_artifact()
    valid_task = make_task_artifact()
    req = make_implement_request(
        spec_artifact=valid_spec,
        plan_artifact=valid_plan,
        task_artifact=valid_task,
        language="",
    )
    val_res = agent.validate(req)
    assert not val_res.valid
    paths = [err.details.get("path") for err in val_res.errors]
    assert "input.language" in paths
    exec_res = agent.execute(req)
    assert exec_res.status == "REJECTED"
    assert len(gateway.requests) == 0


def test_validate_bad_language_whitespace_only() -> None:
    """Whitespace-only language -> REJECTED/VALIDATION_FAILED."""
    agent, gateway = make_agent_and_gateway([])
    valid_spec = make_spec_artifact()
    valid_plan = make_plan_artifact()
    valid_task = make_task_artifact()
    req = make_implement_request(
        spec_artifact=valid_spec,
        plan_artifact=valid_plan,
        task_artifact=valid_task,
        language="   ",
    )
    val_res = agent.validate(req)
    assert not val_res.valid
    paths = [err.details.get("path") for err in val_res.errors]
    assert "input.language" in paths
    exec_res = agent.execute(req)
    assert exec_res.status == "REJECTED"
    assert len(gateway.requests) == 0


def test_validate_bad_attempt_zero() -> None:
    """attempt = 0 -> REJECTED/VALIDATION_FAILED."""
    agent, gateway = make_agent_and_gateway([])
    valid_spec = make_spec_artifact()
    valid_plan = make_plan_artifact()
    valid_task = make_task_artifact()
    req = make_implement_request(
        spec_artifact=valid_spec,
        plan_artifact=valid_plan,
        task_artifact=valid_task,
        metadata={"attempt": 0},
    )
    val_res = agent.validate(req)
    assert not val_res.valid
    paths = [err.details.get("path") for err in val_res.errors]
    assert "metadata.attempt" in paths
    exec_res = agent.execute(req)
    assert exec_res.status == "REJECTED"
    assert len(gateway.requests) == 0


def test_validate_bad_attempt_bool_true() -> None:
    """attempt = True (bool) -> REJECTED/VALIDATION_FAILED."""
    agent, gateway = make_agent_and_gateway([])
    valid_spec = make_spec_artifact()
    valid_plan = make_plan_artifact()
    valid_task = make_task_artifact()
    req = make_implement_request(
        spec_artifact=valid_spec,
        plan_artifact=valid_plan,
        task_artifact=valid_task,
        metadata={"attempt": True},
    )
    val_res = agent.validate(req)
    assert not val_res.valid
    paths = [err.details.get("path") for err in val_res.errors]
    assert "metadata.attempt" in paths
    exec_res = agent.execute(req)
    assert exec_res.status == "REJECTED"
    assert len(gateway.requests) == 0


def test_validate_bad_attempt_string() -> None:
    """attempt = "1" (string) -> REJECTED/VALIDATION_FAILED."""
    agent, gateway = make_agent_and_gateway([])
    valid_spec = make_spec_artifact()
    valid_plan = make_plan_artifact()
    valid_task = make_task_artifact()
    req = make_implement_request(
        spec_artifact=valid_spec,
        plan_artifact=valid_plan,
        task_artifact=valid_task,
        metadata={"attempt": "1"},
    )
    val_res = agent.validate(req)
    assert not val_res.valid
    paths = [err.details.get("path") for err in val_res.errors]
    assert "metadata.attempt" in paths
    exec_res = agent.execute(req)
    assert exec_res.status == "REJECTED"
    assert len(gateway.requests) == 0


def test_validate_spec_artifact_without_text_content() -> None:
    """SPEC artifact without text content -> REJECTED/VALIDATION_FAILED."""
    agent, gateway = make_agent_and_gateway([])
    valid_plan = make_plan_artifact()
    valid_task = make_task_artifact()
    spec_bad = Artifact(
        id="spec-1",
        type="SPEC",
        name="SPEC.md",
        version="1",
        content={"summary": "no text"},
        created_by="agent-spec",
        created_at=T_AWARE,
    )
    req = AgentRequest(
        request_id="req-12",
        task_id="task-12",
        project_id="proj-12",
        workflow_id="software-development",
        agent_id="agent-implement",
        input={"taskItemId": "T1", "ref": "main"},
        context={"project": {}},
        artifacts=[spec_bad, valid_plan, valid_task],
        metadata={"attempt": 1},
    )
    val_res = agent.validate(req)
    assert not val_res.valid
    paths = [err.details.get("path") for err in val_res.errors]
    assert "artifacts[0].content.text" in paths
    exec_res = agent.execute(req)
    assert exec_res.status == "REJECTED"
    assert len(gateway.requests) == 0


def test_validate_plan_artifact_without_text_content() -> None:
    """PLAN artifact without text content -> REJECTED/VALIDATION_FAILED."""
    agent, gateway = make_agent_and_gateway([])
    valid_spec = make_spec_artifact()
    valid_task = make_task_artifact()
    plan_bad = Artifact(
        id="plan-1",
        type="PLAN",
        name="PLAN.md",
        version="1",
        content={"summary": "no text"},
        created_by="agent-plan",
        created_at=T_AWARE,
    )
    req = AgentRequest(
        request_id="req-13",
        task_id="task-13",
        project_id="proj-13",
        workflow_id="software-development",
        agent_id="agent-implement",
        input={"taskItemId": "T1", "ref": "main"},
        context={"project": {}},
        artifacts=[valid_spec, plan_bad, valid_task],
        metadata={"attempt": 1},
    )
    val_res = agent.validate(req)
    assert not val_res.valid
    paths = [err.details.get("path") for err in val_res.errors]
    assert "artifacts[1].content.text" in paths
    exec_res = agent.execute(req)
    assert exec_res.status == "REJECTED"
    assert len(gateway.requests) == 0


def test_validate_task_artifact_without_text_content() -> None:
    """TASK artifact without text content -> REJECTED/VALIDATION_FAILED."""
    agent, gateway = make_agent_and_gateway([])
    valid_spec = make_spec_artifact()
    valid_plan = make_plan_artifact()
    task_bad = Artifact(
        id="task-1",
        type="TASK",
        name="TASK.md",
        version="1",
        content={"summary": "no text"},
        created_by="agent-task",
        created_at=T_AWARE,
    )
    req = AgentRequest(
        request_id="req-14",
        task_id="task-14",
        project_id="proj-14",
        workflow_id="software-development",
        agent_id="agent-implement",
        input={"taskItemId": "T1", "ref": "main"},
        context={"project": {}},
        artifacts=[valid_spec, valid_plan, task_bad],
        metadata={"attempt": 1},
    )
    val_res = agent.validate(req)
    assert not val_res.valid
    paths = [err.details.get("path") for err in val_res.errors]
    assert "artifacts[2].content.text" in paths
    exec_res = agent.execute(req)
    assert exec_res.status == "REJECTED"
    assert len(gateway.requests) == 0


def test_validate_unknown_artifact_type() -> None:
    """Unknown artifact type -> REJECTED/VALIDATION_FAILED."""
    agent, gateway = make_agent_and_gateway([])
    valid_spec = make_spec_artifact()
    valid_plan = make_plan_artifact()
    valid_task = make_task_artifact()
    unknown = Artifact(
        id="unknown-1",
        type="UNKNOWN",
        name="UNKNOWN.md",
        version="1",
        content={"text": "text"},
        created_by="agent-other",
        created_at=T_AWARE,
    )
    req = AgentRequest(
        request_id="req-15",
        task_id="task-15",
        project_id="proj-15",
        workflow_id="software-development",
        agent_id="agent-implement",
        input={"taskItemId": "T1", "ref": "main"},
        context={"project": {}},
        artifacts=[valid_spec, valid_plan, valid_task, unknown],
        metadata={"attempt": 1},
    )
    val_res = agent.validate(req)
    assert not val_res.valid
    paths = [err.details.get("path") for err in val_res.errors]
    assert "artifacts[3].type" in paths
    exec_res = agent.execute(req)
    assert exec_res.status == "REJECTED"
    assert len(gateway.requests) == 0


def test_validate_spec_version_zero() -> None:
    """SPEC version '0' -> REJECTED/VALIDATION_FAILED."""
    agent, gateway = make_agent_and_gateway([])
    valid_plan = make_plan_artifact()
    valid_task = make_task_artifact()
    spec_bad = make_spec_artifact(version="0")
    req = AgentRequest(
        request_id="req-16",
        task_id="task-16",
        project_id="proj-16",
        workflow_id="software-development",
        agent_id="agent-implement",
        input={"taskItemId": "T1", "ref": "main"},
        context={"project": {}},
        artifacts=[spec_bad, valid_plan, valid_task],
        metadata={"attempt": 1},
    )
    val_res = agent.validate(req)
    assert not val_res.valid
    paths = [err.details.get("path") for err in val_res.errors]
    assert "artifacts[0].version" in paths
    exec_res = agent.execute(req)
    assert exec_res.status == "REJECTED"
    assert len(gateway.requests) == 0


def test_validate_spec_version_v1() -> None:
    """SPEC version 'v1' -> REJECTED/VALIDATION_FAILED."""
    agent, gateway = make_agent_and_gateway([])
    valid_plan = make_plan_artifact()
    valid_task = make_task_artifact()
    spec_bad = make_spec_artifact(version="v1")
    req = AgentRequest(
        request_id="req-17",
        task_id="task-17",
        project_id="proj-17",
        workflow_id="software-development",
        agent_id="agent-implement",
        input={"taskItemId": "T1", "ref": "main"},
        context={"project": {}},
        artifacts=[spec_bad, valid_plan, valid_task],
        metadata={"attempt": 1},
    )
    val_res = agent.validate(req)
    assert not val_res.valid
    paths = [err.details.get("path") for err in val_res.errors]
    assert "artifacts[0].version" in paths
    exec_res = agent.execute(req)
    assert exec_res.status == "REJECTED"
    assert len(gateway.requests) == 0


def test_validate_spec_version_1_2() -> None:
    """SPEC version '1.2' -> REJECTED/VALIDATION_FAILED."""
    agent, gateway = make_agent_and_gateway([])
    valid_plan = make_plan_artifact()
    valid_task = make_task_artifact()
    spec_bad = make_spec_artifact(version="1.2")
    req = AgentRequest(
        request_id="req-18",
        task_id="task-18",
        project_id="proj-18",
        workflow_id="software-development",
        agent_id="agent-implement",
        input={"taskItemId": "T1", "ref": "main"},
        context={"project": {}},
        artifacts=[spec_bad, valid_plan, valid_task],
        metadata={"attempt": 1},
    )
    val_res = agent.validate(req)
    assert not val_res.valid
    paths = [err.details.get("path") for err in val_res.errors]
    assert "artifacts[0].version" in paths
    exec_res = agent.execute(req)
    assert exec_res.status == "REJECTED"
    assert len(gateway.requests) == 0


def test_validate_spec_plan_task_content_size_limit() -> None:
    """Combined SPEC+PLAN+TASK content exceeding limit -> REJECTED/VALIDATION_FAILED."""
    from asf.agents.implement.agent import MAX_CODE_REPLY_CHARS
    agent, gateway = make_agent_and_gateway([])
    large_text = "x" * (MAX_CODE_REPLY_CHARS + 100)
    valid_spec = make_spec_artifact(text=large_text)
    valid_plan = make_plan_artifact()
    valid_task = make_task_artifact()
    req = AgentRequest(
        request_id="req-19",
        task_id="task-19",
        project_id="proj-19",
        workflow_id="software-development",
        agent_id="agent-implement",
        input={"taskItemId": "T1", "ref": "main"},
        context={"project": {}},
        artifacts=[valid_spec, valid_plan, valid_task],
        metadata={"attempt": 1},
    )
    val_res = agent.validate(req)
    assert not val_res.valid
    paths = [err.details.get("path") for err in val_res.errors]
    assert "artifacts" in paths
    exec_res = agent.execute(req)
    assert exec_res.status == "REJECTED"
    assert len(gateway.requests) == 0