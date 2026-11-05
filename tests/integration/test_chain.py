"""Integration tests for the full Spec -> Plan -> Task -> Implement chain."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from asf.agents.base import AgentRuntime
from asf.agents.implement.factory import build_implement_agent
from asf.agents.plan.factory import build_plan_agent
from asf.agents.spec.factory import build_spec_agent
from asf.agents.task.factory import build_task_agent
from asf.configuration.platform import AgentSettings, PlatformConfig
from asf.contracts.models import AgentRequest, Artifact
from asf.models.fake import ScriptedModelGateway
from asf.tools.fake import InMemoryRepository

REPO_ROOT = Path(__file__).resolve().parents[2]
T_AWARE = datetime(2026, 10, 20, 14, 0, 0, tzinfo=timezone.utc)

# Shared platform config and templates_dir for factory calls.
# These chain suites script the legacy JSON code format end to end:
# pin it (and no in-agent repair loop) explicitly — the blocks
# format and the repair loop have their own suites.
PLATFORM = PlatformConfig(
    agents={
        "implement": AgentSettings(
            settings={"editFormat": "json", "repairAttempts": 0},
        ),
        "fix": AgentSettings(
            settings={"editFormat": "json", "repairAttempts": 0},
        ),
    }
)
TEMPLATES_DIR = REPO_ROOT / "templates"


def counter_id(prefix: str = "id-") -> callable:
    """Create a counter function for generating unique IDs."""
    count = 0

    def _next() -> str:
        nonlocal count
        count += 1
        return f"{prefix}{count}"

    return _next


def make_spec_artifact() -> Artifact:
    """Create a sample SPEC artifact."""
    spec_text = """# SPEC: Test Feature

## Background / Goal
This is a test specification for a simple calculator module.

## Scope (in / out)
In scope: Basic arithmetic functions (add, subtract, multiply, divide).
Out of scope: Advanced math functions, scientific calculations.

## Functional requirements
- REQ-1: Implement add(a, b) function returning a + b
- REQ-2: Implement subtract(a, b) function returning a - b
- REQ-3: Implement multiply(a, b) function returning a * b
- REQ-4: Implement divide(a, b) function returning a / b or raising ValueError for division by zero

## Non-functional requirements
- Python 3.10+ compatible
- No external dependencies
- Functions handle integer and float inputs

## Acceptance criteria
- All functions return correct results for valid inputs
- Division by zero raises ValueError with descriptive message
- Functions are documented with docstrings

## Open questions
None.

## Revision history
- v1: Initial specification.
"""
    return Artifact(
        id="spec-1",
        type="SPEC",
        name="SPEC.md",
        version="1",
        content={"format": "markdown", "text": spec_text},
        created_by="agent-spec",
        created_at=T_AWARE,
    )


def make_plan_artifact() -> Artifact:
    """Create a sample PLAN artifact."""
    plan_text = """# PLAN: Test Feature

## Linked SPEC
ID: spec-1
Version: 1

## Scope and out of scope
In scope: Basic arithmetic functions (add, subtract, multiply, divide).
Out of scope: Advanced math functions, scientific calculations.

## Approach / architecture
Simple module with four functions in a single file.

## Impacted components
- calculator.py (new file)

## Milestones
### M1: Setup
- Deliverables: calculator.py
- Acceptance criteria: All functions implemented and tested
- Depends on: none

## Testing strategy
Unit tests for all functions covering valid inputs and edge cases.

## Risks & mitigations
- Risk: Division by zero. Mitigation: Explicit check and ValueError.

## Open questions
None.

## Revision history
- v1: Initial plan.
"""
    return Artifact(
        id="plan-1",
        type="PLAN",
        name="PLAN.md",
        version="1",
        content={"format": "markdown", "text": plan_text},
        created_by="agent-plan",
        created_at=T_AWARE,
        metadata={
            "template": "plan",
            "specArtifactId": "spec-1",
            "specVersion": "1",
        },
    )


def make_task_artifact() -> Artifact:
    """Create a sample TASK artifact."""
    task_text = json.dumps(
        {
            "tasks": [
                {
                    "id": "T1",
                    "title": "Create calculator module",
                    "milestoneRef": "M1",
                    "description": (
                        "Implement add, subtract, multiply, divide functions in calculator.py"
                    ),
                    "acceptanceCriteria": [
                        "Function add(a, b) returns a + b",
                        "Function subtract(a, b) returns a - b",
                        "Function multiply(a, b) returns a * b",
                        "Function divide(a, b) returns a / b or raises "
                        "ValueError for divide by zero",
                    ],
                    "dependsOn": [],
                    "expectedFiles": ["calculator.py"],
                    "verificationHint": "Run unit tests",
                }
            ]
        },
        indent=2,
    )
    return Artifact(
        id="task-1",
        type="TASK",
        name="TASK.md",
        version="1",
        content={"format": "json", "text": task_text},
        created_by="agent-task",
        created_at=T_AWARE,
    )


def make_spec_request() -> AgentRequest:
    return AgentRequest(
        request_id="req-spec-1",
        task_id="task-1",
        project_id="proj-1",
        workflow_id="software-development",
        agent_id="agent-spec",
        input={"requirement": "Create a calculator module"},
        context={},
        artifacts=[],
        metadata={},
    )


def make_plan_request(spec_artifact: Artifact) -> AgentRequest:
    return AgentRequest(
        request_id="req-plan-1",
        task_id="task-1",
        project_id="proj-1",
        workflow_id="software-development",
        agent_id="agent-plan",
        input={},
        context={"project": {}},
        artifacts=[spec_artifact],
        metadata={},
    )


def make_task_request(spec_artifact: Artifact, plan_artifact: Artifact) -> AgentRequest:
    return AgentRequest(
        request_id="req-task-1",
        task_id="task-1",
        project_id="proj-1",
        workflow_id="software-development",
        agent_id="agent-task",
        input={},
        context={"project": {}},
        artifacts=[spec_artifact, plan_artifact],
        metadata={},
    )


def make_implement_request(
    spec_artifact: Artifact,
    plan_artifact: Artifact,
    task_artifact: Artifact,
    task_item_id: str,
) -> AgentRequest:
    return AgentRequest(
        request_id="req-implement-1",
        task_id="task-1",
        project_id="proj-1",
        workflow_id="software-development",
        agent_id="agent-implement",
        input={"taskItemId": task_item_id, "ref": "main"},
        context={"project": {}},
        artifacts=[spec_artifact, plan_artifact, task_artifact],
        metadata={},
    )


def test_spec_agent_creates_valid_artifact():
    """SpecAgent creates a valid SPEC artifact."""
    spec_reply = """# SPEC: Calculator Module

## Background / Goal
A simple calculator module with basic arithmetic operations.

## Scope (in / out)
In scope: Basic arithmetic functions (add, subtract, multiply, divide).
Out of scope: Advanced math functions, scientific calculations.

## Functional requirements
- REQ-1: Implement add(a, b) function returning a + b
- REQ-2: Implement subtract(a, b) function returning a - b
- REQ-3: Implement multiply(a, b) function returning a * b
- REQ-4: Implement divide(a, b) function returning a / b or raising ValueError for division by zero

## Non-functional requirements
- Python 3.10+ compatible
- No external dependencies
- Functions handle integer and float inputs

## Acceptance criteria
- All functions return correct results for valid inputs
- Division by zero raises ValueError with descriptive message
- Functions are documented with docstrings

## Open questions
None.

## Revision history
- v1: Initial specification.
"""
    gateway = ScriptedModelGateway([spec_reply])
    runtime = AgentRuntime(models=gateway, clock=lambda: T_AWARE, new_id=lambda: "id-1")
    agent = build_spec_agent(runtime, PLATFORM, TEMPLATES_DIR)

    req = make_spec_request()
    res = agent.execute(req)

    assert res.status == "SUCCESS"
    assert len(res.artifacts) == 1
    artifact = res.artifacts[0]
    assert artifact.type == "SPEC"
    assert artifact.version == "1"
    assert "text" in artifact.content
    assert len(artifact.content["text"]) > 0


def test_plan_agent_creates_valid_artifact():
    """PlanAgent creates a valid PLAN artifact from SPEC."""
    spec_art = make_spec_artifact()
    plan_reply = """# PLAN: Calculator Module

## Linked SPEC
ID: spec-1
Version: 1

## Scope and out of scope
In scope: Basic arithmetic functions (add, subtract, multiply, divide).
Out of scope: Advanced math functions, scientific calculations.

## Approach / architecture
Simple module with four functions in a single file.

## Impacted components
- calculator.py (new file)

## Milestones
### M1: Setup
- Deliverables: calculator.py
- Acceptance criteria: All functions implemented and tested
- Depends on: none

## Testing strategy
Unit tests for all functions covering valid inputs and edge cases.

## Risks & mitigations
- Risk: Division by zero. Mitigation: Explicit check and ValueError.

## Open questions
None.

## Revision history
- v1: Initial plan.
"""
    gateway = ScriptedModelGateway([plan_reply])
    runtime = AgentRuntime(models=gateway, clock=lambda: T_AWARE, new_id=lambda: "id-1")
    agent = build_plan_agent(runtime, PLATFORM, TEMPLATES_DIR)

    req = make_plan_request(spec_art)
    res = agent.execute(req)

    assert res.status == "SUCCESS"
    assert len(res.artifacts) == 1
    artifact = res.artifacts[0]
    assert artifact.type == "PLAN"
    assert artifact.version == "1"
    assert "text" in artifact.content


def test_task_agent_creates_valid_artifact():
    """TaskAgent creates a valid TASK artifact from SPEC and PLAN."""
    spec_art = make_spec_artifact()
    plan_art = make_plan_artifact()
    task_reply = json.dumps(
        {
            "tasks": [
                {
                    "id": "T1",
                    "title": "Create calculator module",
                    "milestoneRef": "M1",
                    "description": (
                        "Implement add, subtract, multiply, divide functions in calculator.py"
                    ),
                    "acceptanceCriteria": [
                        "Function add(a, b) returns a + b",
                        "Function subtract(a, b) returns a - b",
                        "Function multiply(a, b) returns a * b",
                        "Function divide(a, b) returns a / b or raises "
                        "ValueError for divide by zero",
                    ],
                    "dependsOn": [],
                    "expectedFiles": ["calculator.py"],
                    "verificationHint": "Run unit tests",
                }
            ]
        },
        indent=2,
    )
    gateway = ScriptedModelGateway([task_reply])
    runtime = AgentRuntime(models=gateway, clock=lambda: T_AWARE, new_id=lambda: "id-1")
    agent = build_task_agent(runtime, PLATFORM, TEMPLATES_DIR)

    req = make_task_request(spec_art, plan_art)
    res = agent.execute(req)

    assert res.status == "SUCCESS"
    assert len(res.artifacts) == 1
    artifact = res.artifacts[0]
    assert artifact.type == "TASK"
    assert artifact.version == "1"
    assert "text" in artifact.content


def test_implement_agent_creates_valid_artifact():
    """ImplementAgent creates a valid CODE artifact from SPEC, PLAN, TASK."""
    spec_art = make_spec_artifact()
    plan_art = make_plan_artifact()
    task_art = make_task_artifact()

    implement_reply = json.dumps(
        {
            "changes": [
                {
                    "path": "calculator.py",
                    "operation": "create",
                    "content": (
                        "def add(a, b):\n    return a + b\n\n"
                        "def subtract(a, b):\n    return a - b\n\n"
                        "def multiply(a, b):\n    return a * b\n\n"
                        "def divide(a, b):\n"
                        "    if b == 0:\n"
                        '        raise ValueError("Cannot divide by zero")\n'
                        "    return a / b\n"
                    ),
                }
            ]
        },
        indent=2,
    )

    gateway = ScriptedModelGateway([implement_reply])
    runtime = AgentRuntime(models=gateway, clock=lambda: T_AWARE, new_id=lambda: "id-1")
    repo = InMemoryRepository()
    agent = build_implement_agent(runtime, PLATFORM, TEMPLATES_DIR, repo)

    req = make_implement_request(spec_art, plan_art, task_art, "T1")
    res = agent.execute(req)

    assert res.status == "SUCCESS"
    assert len(res.artifacts) == 1
    artifact = res.artifacts[0]
    assert artifact.type == "CODE"
    assert artifact.version == "1"
    assert artifact.content["format"] == "json"
    assert "changeSet" in artifact.content
    assert "text" in artifact.content
    changes = artifact.content["changeSet"]["changes"]
    assert len(changes) == 1
    assert changes[0]["path"] == "calculator.py"
    assert changes[0]["operation"] == "create"


def test_full_chain_spec_to_implement():
    """Complete Spec -> Plan -> Task -> Implement chain."""
    # 1. SpecAgent
    spec_reply = make_spec_artifact().content["text"]
    spec_gateway = ScriptedModelGateway([spec_reply])
    spec_runtime = AgentRuntime(models=spec_gateway, clock=lambda: T_AWARE, new_id=lambda: "spec-1")
    spec_agent = build_spec_agent(spec_runtime, PLATFORM, TEMPLATES_DIR)
    spec_req = make_spec_request()
    spec_res = spec_agent.execute(spec_req)
    assert spec_res.status == "SUCCESS"
    spec_art = spec_res.artifacts[0]

    # 2. PlanAgent
    plan_reply = make_plan_artifact().content["text"]
    plan_gateway = ScriptedModelGateway([plan_reply])
    plan_runtime = AgentRuntime(models=plan_gateway, clock=lambda: T_AWARE, new_id=lambda: "plan-1")
    plan_agent = build_plan_agent(plan_runtime, PLATFORM, TEMPLATES_DIR)
    plan_req = make_plan_request(spec_art)
    plan_res = plan_agent.execute(plan_req)
    assert plan_res.status == "SUCCESS"
    plan_art = plan_res.artifacts[0]

    # 3. TaskAgent
    task_reply = make_task_artifact().content["text"]
    task_gateway = ScriptedModelGateway([task_reply])
    task_runtime = AgentRuntime(models=task_gateway, clock=lambda: T_AWARE, new_id=lambda: "task-1")
    task_agent = build_task_agent(task_runtime, PLATFORM, TEMPLATES_DIR)
    task_req = make_task_request(spec_art, plan_art)
    task_res = task_agent.execute(task_req)
    assert task_res.status == "SUCCESS"
    task_art = task_res.artifacts[0]

    # 4. ImplementAgent
    implement_reply = json.dumps(
        {
            "changes": [
                {
                    "path": "calculator.py",
                    "operation": "create",
                    "content": (
                        "def add(a, b):\n    return a + b\n\n"
                        "def subtract(a, b):\n    return a - b\n\n"
                        "def multiply(a, b):\n    return a * b\n\n"
                        "def divide(a, b):\n"
                        "    if b == 0:\n"
                        '        raise ValueError("Cannot divide by zero")\n'
                        "    return a / b\n"
                    ),
                }
            ]
        },
        indent=2,
    )
    implement_gateway = ScriptedModelGateway([implement_reply])
    implement_runtime = AgentRuntime(
        models=implement_gateway, clock=lambda: T_AWARE, new_id=lambda: "code-1"
    )
    repo = InMemoryRepository()
    implement_agent = build_implement_agent(implement_runtime, PLATFORM, TEMPLATES_DIR, repo)
    implement_req = make_implement_request(spec_art, plan_art, task_art, "T1")
    implement_res = implement_agent.execute(implement_req)

    print(f"Implement status: {implement_res.status}")
    if implement_res.errors:
        for e in implement_res.errors:
            print(f"Error: {e.code} - {e.message} - {e.details}")

    assert implement_res.status == "SUCCESS"
    assert len(implement_res.artifacts) == 1
    code_art = implement_res.artifacts[0]
    assert code_art.type == "CODE"
    assert code_art.content["format"] == "json"
    assert "changeSet" in code_art.content
    assert "text" in code_art.content


def test_implement_chain_traceability_links():
    """All traceability links correctly established."""
    spec_art = make_spec_artifact()
    plan_art = make_plan_artifact()
    task_art = make_task_artifact()

    implement_reply = json.dumps(
        {
            "changes": [
                {
                    "path": "calculator.py",
                    "operation": "create",
                    "content": "def add(a, b):\n    return a + b\n",
                }
            ]
        },
        indent=2,
    )

    gateway = ScriptedModelGateway([implement_reply])
    runtime = AgentRuntime(models=gateway, clock=lambda: T_AWARE, new_id=lambda: "id-1")
    repo = InMemoryRepository()
    agent = build_implement_agent(runtime, PLATFORM, TEMPLATES_DIR, repo)
    req = make_implement_request(spec_art, plan_art, task_art, "T1")
    res = agent.execute(req)

    assert res.status == "SUCCESS"
    artifact = res.artifacts[0]

    meta = artifact.metadata
    assert meta["specArtifactId"] == spec_art.id
    assert meta["planArtifactId"] == plan_art.id
    assert meta["taskArtifactId"] == task_art.id
    assert meta["taskVersion"] == task_art.version
    assert meta["baseRef"] == "main"
    assert meta["taskItemId"] == "T1"
    assert "generatedAt" in meta


def test_implement_task_item_not_found():
    """ImplementAgent fails when task item not found."""
    spec_art = make_spec_artifact()
    plan_art = make_plan_artifact()
    task_art = make_task_artifact()

    implement_reply = json.dumps(
        {
            "changes": [
                {
                    "path": "calculator.py",
                    "operation": "create",
                    "content": "def add(a, b):\n    return a + b\n",
                }
            ]
        },
        indent=2,
    )

    gateway = ScriptedModelGateway([implement_reply])
    runtime = AgentRuntime(models=gateway, clock=lambda: T_AWARE, new_id=lambda: "id-1")
    repo = InMemoryRepository()
    agent = build_implement_agent(runtime, PLATFORM, TEMPLATES_DIR, repo)
    req = make_implement_request(spec_art, plan_art, task_art, "T999")
    res = agent.execute(req)

    assert res.status == "FAILED"
    assert res.errors[0].code == "LLM_INVALID_RESPONSE"
    assert "not found in TASK artifact" in res.errors[0].message


def test_implement_with_existing_repository_files():
    """ImplementAgent with existing files in repository."""
    repo = InMemoryRepository({"main": {"calculator.py": "def add(a, b):\n    return a + b\n"}})

    implement_reply = json.dumps(
        {
            "changes": [
                {
                    "path": "calculator.py",
                    "operation": "modify",
                    "content": (
                        "def add(a, b):\n    return a + b\n\n"
                        "def subtract(a, b):\n    return a - b\n"
                    ),
                }
            ]
        },
        indent=2,
    )

    gateway = ScriptedModelGateway([implement_reply])
    runtime = AgentRuntime(models=gateway, clock=lambda: T_AWARE, new_id=lambda: "id-1")
    agent = build_implement_agent(runtime, PLATFORM, TEMPLATES_DIR, repo)

    spec_art = make_spec_artifact()
    plan_art = make_plan_artifact()
    task_art = make_task_artifact()
    req = make_implement_request(spec_art, plan_art, task_art, "T1")
    res = agent.execute(req)

    assert res.status == "SUCCESS"
    artifact = res.artifacts[0]
    changes = artifact.content["changeSet"]["changes"]
    assert changes[0]["operation"] == "modify"


def test_chain_artifact_versions():
    """Artifact versions correctly propagated through the chain."""
    spec_art = make_spec_artifact()
    plan_art = make_plan_artifact()
    task_art = make_task_artifact()

    implement_reply = json.dumps(
        {
            "changes": [
                {
                    "path": "calculator.py",
                    "operation": "create",
                    "content": "def add(a, b):\n    return a + b\n",
                }
            ]
        },
        indent=2,
    )

    gateway = ScriptedModelGateway([implement_reply])
    runtime = AgentRuntime(models=gateway, clock=lambda: T_AWARE, new_id=lambda: "id-1")
    repo = InMemoryRepository()
    agent = build_implement_agent(runtime, PLATFORM, TEMPLATES_DIR, repo)
    req = make_implement_request(spec_art, plan_art, task_art, "T1")
    res = agent.execute(req)

    assert res.status == "SUCCESS"
    artifact = res.artifacts[0]

    assert artifact.version == "1"
    assert artifact.metadata["specVersion"] == spec_art.version
    assert artifact.metadata["planVersion"] == plan_art.version
    assert artifact.metadata["taskVersion"] == task_art.version


def test_implement_multiple_task_items():
    """Implementing multiple task items from the same TASK artifact."""
    spec_art = make_spec_artifact()
    plan_art = make_plan_artifact()
    # Task artifact with two tasks
    task_art = Artifact(
        id="task-1",
        type="TASK",
        name="TASK.md",
        version="1",
        content={
            "format": "json",
            "text": json.dumps(
                {
                    "tasks": [
                        {
                            "id": "T1",
                            "title": "Create calculator module",
                            "milestoneRef": "M1",
                            "description": "Implement add function",
                            "acceptanceCriteria": ["Function add(a, b) returns a + b"],
                            "dependsOn": [],
                            "expectedFiles": ["calculator.py"],
                            "verificationHint": "Run unit tests",
                        },
                        {
                            "id": "T2",
                            "title": "Create test module",
                            "milestoneRef": "M1",
                            "description": "Write unit tests",
                            "acceptanceCriteria": ["Tests for add function"],
                            "dependsOn": ["T1"],
                            "expectedFiles": ["test_calculator.py"],
                            "verificationHint": "Run pytest",
                        },
                    ]
                },
                indent=2,
            ),
        },
        created_by="agent-task",
        created_at=T_AWARE,
    )

    implement_reply_t1 = json.dumps(
        {
            "changes": [
                {
                    "path": "calculator.py",
                    "operation": "create",
                    "content": "def add(a, b):\n    return a + b\n",
                }
            ]
        },
        indent=2,
    )

    implement_reply_t2 = json.dumps(
        {
            "changes": [
                {
                    "path": "test_calculator.py",
                    "operation": "create",
                    "content": (
                        "import unittest\n"
                        "from calculator import add\n\n"
                        "class TestCalculator(unittest.TestCase):\n"
                        "    def test_add(self):\n"
                        "        self.assertEqual(add(1, 2), 3)\n"
                    ),
                }
            ]
        },
        indent=2,
    )

    gateway = ScriptedModelGateway([implement_reply_t1, implement_reply_t2])
    nid = counter_id("id-")
    runtime = AgentRuntime(models=gateway, clock=lambda: T_AWARE, new_id=nid)
    repo = InMemoryRepository()
    agent = build_implement_agent(runtime, PLATFORM, TEMPLATES_DIR, repo)

    # Implement T1
    req1 = make_implement_request(spec_art, plan_art, task_art, "T1")
    res1 = agent.execute(req1)
    assert res1.status == "SUCCESS"

    # Implement T2
    req2 = make_implement_request(spec_art, plan_art, task_art, "T2")
    res2 = agent.execute(req2)
    assert res2.status == "SUCCESS"

    assert len(res1.artifacts) == 1
    assert len(res2.artifacts) == 1
    assert res1.artifacts[0].id != res2.artifacts[0].id


def test_implement_output_contains_rendered_text():
    """Output artifact contains both JSON and rendered text."""
    spec_art = make_spec_artifact()
    plan_art = make_plan_artifact()
    task_art = make_task_artifact()

    implement_reply = json.dumps(
        {
            "changes": [
                {
                    "path": "calculator.py",
                    "operation": "create",
                    "content": "def add(a, b):\n    return a + b\n",
                }
            ]
        },
        indent=2,
    )

    gateway = ScriptedModelGateway([implement_reply])
    runtime = AgentRuntime(models=gateway, clock=lambda: T_AWARE, new_id=lambda: "id-1")
    repo = InMemoryRepository()
    agent = build_implement_agent(runtime, PLATFORM, TEMPLATES_DIR, repo)
    req = make_implement_request(spec_art, plan_art, task_art, "T1")
    res = agent.execute(req)

    assert res.status == "SUCCESS"
    artifact = res.artifacts[0]

    assert "changeSet" in artifact.content
    assert "text" in artifact.content

    text = artifact.content["text"]
    assert "# CODE: Implementation" in text
    assert "calculator.py" in text
    assert "def add(a, b):" in text
    assert "```python" in text
