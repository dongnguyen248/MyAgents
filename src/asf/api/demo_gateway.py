"""Deterministic per-agent replies for the demo backend.

Replies are chosen per agent from the system prompt and use the exact
canned SPEC/PLAN/TASK/CODE/CODE_REVIEW formats the agents' own tests
use. Extracted from demo.py so the assembly module stays reviewable;
the routing keys are substrings of each agent's packaged prompts.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from asf.agents.loading import load_plan_template, load_spec_template
from asf.contracts.models import ModelRequest, ModelResponse
from asf.models.fake import ScriptedModelGateway

__all__ = ["DemoRoutingGateway"]

_TASK_REPLY = json.dumps(
    {
        "tasks": [
            {
                "id": "T1",
                "title": "Create the demo module",
                "milestoneRef": "M1",
                "description": (
                    "Implement the demo module described by the SPEC, covering "
                    "REQ-1 and REQ-2; run the project tests"
                ),
                "acceptanceCriteria": [
                    "REQ-1: The demo module exists and imports cleanly",
                    "REQ-2: Invalid input is rejected with a clear error",
                ],
                "dependsOn": [],
                "expectedFiles": ["calculator.py"],
                "verificationHint": "Run the project test commands",
            }
        ],
    },
    indent=2,
)

_CODE_REPLY = """CREATE: calculator.py
<<<<<<< FILE
def add(a, b):
    return a + b
>>>>>>> FILE
"""

_FIX_REPLY = """FILE: calculator.py
<<<<<<< SEARCH
def add(a, b):
    return a + b
=======
def add(a, b):
    return a + b
>>>>>>> REPLACE
"""

_REVIEW_REPLY = '{"findings": [], "verdict": "APPROVE"}'

_ARTIFACT_REVIEW_REPLY = '{"findings": [], "summary": "Scripted artifact review: no findings."}'

_STATIC_REPLIES = (
    ("breaking down implementation plans", _TASK_REPLY),
    ("implementing code changes", _CODE_REPLY),
    ("You review exactly one task", _REVIEW_REPLY),
    ("You fix one task item", _FIX_REPLY),
    ("independent artifact reviewer", _ARTIFACT_REVIEW_REPLY),
)


class DemoRoutingGateway:
    """Deterministic per-agent replies over one ScriptedModelGateway."""

    def __init__(self, templates_dir: Path) -> None:
        self._templates_dir = templates_dir
        self.requests: list[ModelRequest] = []

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        system = request.messages[0].content
        user = request.messages[-1].content
        reply = self._reply_for(system, user)
        return ScriptedModelGateway([reply]).complete(request)

    def _reply_for(self, system: str, user: str) -> str:
        if "senior business analyst" in system:
            return self._spec_reply(user)
        if "senior software architect" in system:
            return self._plan_reply(user)
        for marker, reply in _STATIC_REPLIES:
            if marker in system:
                return reply
        # Defensive: every demo agent must be routed above.
        raise RuntimeError(f"No demo reply routed for system prompt: {system[:60]}")

    def _spec_reply(self, user: str) -> str:
        template = load_spec_template(self._templates_dir)
        revised = "## Reviewer feedback" in user
        body = "Revised demo specification." if revised else "Initial demo specification."
        sections = {
            "## Functional requirements": (
                "- REQ-1: Provide the demo calculation.\n"
                "- REQ-2: Reject invalid input with a clear error."
            ),
            "## Acceptance criteria": (
                "- REQ-1: The demo calculation returns the expected result.\n"
                "- REQ-2: Invalid input is rejected with a clear error."
            ),
        }
        return "# SPEC: Demo\n\n" + "\n\n".join(
            f"{heading}\n{sections.get(heading, body)}" for heading in template.required_sections
        )

    def _plan_reply(self, user: str) -> str:
        template = load_plan_template(self._templates_dir)
        linked = re.search(r"## Linked SPEC\nID: ([^\n]+)\nVersion: ([^\n]+)", user)
        linked_text = (
            f"ID: {linked[1]}\nVersion: {linked[2]}" if linked else "ID: unknown\nVersion: 1"
        )
        sections = {
            "## Linked SPEC": linked_text,
            "## Approach / architecture": "Demo approach covering REQ-1 and REQ-2.",
            "## Milestones": (
                "### M1: Demonstrate the approved SPEC handoff\n"
                "- Deliverables: Demo PLAN\n"
                "- Acceptance criteria: PLAN uses the approved SPEC\n"
                "- Depends on: none"
            ),
        }
        return "# PLAN: Demo\n\n" + "\n\n".join(
            f"{heading}\n{sections.get(heading, 'Deterministic demo plan content.')}"
            for heading in template.required_sections
        )
