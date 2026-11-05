from __future__ import annotations

import json

import pytest

from asf.api.decomposer import RequirementDecomposer
from asf.models.fake import ScriptedModelGateway

_PART = "Implement the specified behaviour completely, with tests. "


def _decomposer(reply: str) -> tuple[RequirementDecomposer, ScriptedModelGateway]:
    gateway = ScriptedModelGateway([reply])
    return RequirementDecomposer(gateway), gateway


def test_split_parses_context_parts_and_full_requirements():
    payload = {
        "context": "Overall: build the messenger core in Python.",
        "parts": [
            {"title": "Auth module", "requirement": _PART + "Login and sessions."},
            {"title": "Chat module", "requirement": _PART + "Rooms and messages."},
        ],
    }
    decomposer, gateway = _decomposer(json.dumps(payload))
    plan = decomposer.split(title="Messenger", requirement="x" * 20_000)
    assert plan.context.startswith("Overall:")
    assert [part.title for part in plan.parts] == ["Auth module", "Chat module"]
    full = plan.full_requirement(plan.parts[0])
    assert full.startswith("Overall: build the messenger core")
    assert full.endswith("Login and sessions.")
    # The decomposition call is attributed to the decomposer, which
    # the routing gateway resolves to the shared (strong) model.
    assert gateway.requests[0].metadata["agentId"] == "decomposer"


def test_split_accepts_a_code_fenced_reply():
    payload = {
        "context": "",
        "parts": [
            {"title": "One", "requirement": _PART + "First."},
            {"title": "Two", "requirement": _PART + "Second."},
        ],
    }
    decomposer, _ = _decomposer(f"```json\n{json.dumps(payload)}\n```")
    plan = decomposer.split(title="T", requirement="x" * 20_000)
    assert len(plan.parts) == 2
    assert plan.full_requirement(plan.parts[0]) == _PART + "First."


@pytest.mark.parametrize("reply", ["not json at all", "{broken", "[1, 2]"])
def test_split_rejects_non_object_replies(reply: str):
    decomposer, _ = _decomposer(reply)
    with pytest.raises(ValueError, match="Decomposition"):
        decomposer.split(title="T", requirement="x" * 20_000)


def test_split_rejects_wrong_part_counts():
    one = {"parts": [{"title": "Only", "requirement": _PART + "Alone."}]}
    decomposer, _ = _decomposer(json.dumps(one))
    with pytest.raises(ValueError, match="2..6 parts"):
        decomposer.split(title="T", requirement="x" * 20_000)

    seven = {
        "parts": [{"title": f"P{i}", "requirement": _PART + f"Part {i}."} for i in range(7)],
    }
    decomposer, _ = _decomposer(json.dumps(seven))
    with pytest.raises(ValueError, match="2..6 parts"):
        decomposer.split(title="T", requirement="x" * 20_000)


def test_split_rejects_bad_parts():
    too_long = {
        "parts": [
            {"title": "Huge", "requirement": "y" * 12_001},
            {"title": "Fine", "requirement": _PART + "Ok."},
        ],
    }
    decomposer, _ = _decomposer(json.dumps(too_long))
    with pytest.raises(ValueError, match="exceeds"):
        decomposer.split(title="T", requirement="x" * 20_000)

    too_short = {
        "parts": [
            {"title": "Tiny", "requirement": "Do it."},
            {"title": "Fine", "requirement": _PART + "Ok."},
        ],
    }
    decomposer, _ = _decomposer(json.dumps(too_short))
    with pytest.raises(ValueError, match="too short"):
        decomposer.split(title="T", requirement="x" * 20_000)

    no_title = {
        "parts": [
            {"title": " ", "requirement": _PART + "Ok."},
            {"title": "Fine", "requirement": _PART + "Ok."},
        ],
    }
    decomposer, _ = _decomposer(json.dumps(no_title))
    with pytest.raises(ValueError, match="no title"):
        decomposer.split(title="T", requirement="x" * 20_000)
