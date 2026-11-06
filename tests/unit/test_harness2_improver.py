"""Tests for the real improver (Phase 11b, H3): prompt templates,
GatewayImprover, and fault injection through the Stage and the
full Parallel/Sequential engine. All gateways are scripted fakes;
no real model is called.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from asf.contracts.models import ModelRequest, ModelResponse, ModelUsage
from asf.models.errors import ModelGatewayError
from harness.harness2.adapters import SpecTaskAdapter
from harness.harness2.bundle import default_tree
from harness.harness2.context import build_evidence
from harness.harness2.demo import SOLVER_MARKER, HarnessAwareGateway
from harness.harness2.improver import GatewayImprover
from harness.harness2.ledger import Ledger
from harness.harness2.prompts import (
    FORBIDDEN_MEASUREMENT_WORDS,
    PROMPT_NAMES,
    MissionInputs,
    check_prompt_text,
    load_prompt,
    mission_prompt,
)
from harness.harness2.recursion import (
    Loop,
    ModeOptions,
    StageRequest,
    StageResult,
    run_parallel,
    run_stage,
)
from harness.harness2.surface import SYSTEM_PATH, Tree
from tests.unit.test_harness2_recursion import FakeAdapter

FROZEN_LINE = "Return only the final markdown document."
ANCHOR = (
    "5. Return only the final markdown document. "
    "Do not wrap the response in conversational text or external greetings."
)


class ScriptedGateway:
    """Improver gateway fake: a handler computes each reply."""

    def __init__(self, handler: Callable[[ModelRequest], str]) -> None:
        self._handler = handler
        self.requests: list[ModelRequest] = []

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        content = self._handler(request)
        return ModelResponse(
            content=content,
            model="scripted-improver",
            usage=ModelUsage(prompt_tokens=10, completion_tokens=5),
            finish_reason="stop",
            metadata={},
        )


def _evidence():
    return build_evidence("t1", [])


def _spec_loop(gateway: ScriptedGateway, tmp_path: Path) -> Loop:
    adapter = SpecTaskAdapter(runs_root=tmp_path / "runs")
    improver = GatewayImprover(gateway, agent="spec")
    return Loop(adapter=adapter, improver=improver, ledger=Ledger())


def _spec_stage(loop: Loop, harness: Tree) -> StageResult:
    request = StageRequest("inv0", "invariant", _evidence(), harness)
    return run_stage(loop, request)


# -- prompt templates -------------------------------------------------------


@pytest.mark.parametrize("name", PROMPT_NAMES)
def test_templates_load_and_describe_only_the_work(name: str) -> None:
    text = load_prompt(name)
    assert text.strip()
    for word in FORBIDDEN_MEASUREMENT_WORDS:
        assert word not in text.lower()


def test_wording_check_rejects_measurement_words() -> None:
    with pytest.raises(ValueError, match="measurement"):
        check_prompt_text("tampered", "compare against the benchmark rubric")


def test_mission_prompt_is_fully_filled() -> None:
    text = mission_prompt(
        "propose_inv",
        MissionInputs(
            agent="spec",
            evidence="EVIDENCE TEXT",
            harness={"prompts/system.md": "system body"},
        ),
    )
    assert "EVIDENCE TEXT" in text
    assert "===== prompts/system.md =====\nsystem body" in text
    assert "instructions/guardrails.md" in text
    assert "{evidence}" not in text and "{harness}" not in text


def test_unknown_mission_and_template_raise() -> None:
    gateway = ScriptedGateway(lambda request: "notes only")
    improver = GatewayImprover(gateway, agent="spec")
    with pytest.raises(ValueError, match="unknown improver mission"):
        improver.improve("select", _evidence(), {})
    with pytest.raises(ValueError, match="unknown improver prompt"):
        load_prompt("select")


# -- GatewayImprover behaviour ----------------------------------------------


def _marker_edit(request: ModelRequest) -> str:
    return (
        "The base rollout dropped the last template section; adding the marker line.\n"
        f"FILE: {SYSTEM_PATH}\n"
        "<<<<<<< SEARCH\n"
        f"{ANCHOR}\n"
        "=======\n"
        f"{ANCHOR}\n"
        f"{SOLVER_MARKER}\n"
        ">>>>>>> REPLACE\n"
    )


def test_gateway_improver_applies_blocks_and_keeps_notes() -> None:
    gateway = ScriptedGateway(_marker_edit)
    improver = GatewayImprover(gateway, agent="spec")
    base = default_tree("spec")
    reply = improver.improve("invariant", _evidence(), base)
    assert SOLVER_MARKER in reply.tree[SYSTEM_PATH]
    assert "dropped the last template section" in reply.notes
    request = gateway.requests[0]
    assert request.metadata["mission"] == "invariant"
    assert request.metadata["agentId"] == "harness2-improver"
    assert "Evidence for task 't1'" in request.messages[0].content


def test_gateway_improver_creates_a_new_skill_file() -> None:
    def handler(request: ModelRequest) -> str:
        return (
            "Adding a probe skill.\n"
            "CREATE: skills/probe/SKILL.md\n"
            "<<<<<<< FILE\n"
            "Probe skill body.\n"
            ">>>>>>> FILE\n"
        )

    improver = GatewayImprover(ScriptedGateway(handler), agent="spec")
    reply = improver.improve("domain", _evidence(), default_tree("spec"))
    assert reply.tree["skills/probe/SKILL.md"] == "Probe skill body.\n"


def test_gateway_improver_notes_only_reply_is_a_noop() -> None:
    gateway = ScriptedGateway(lambda request: "Nothing defensible to change.")
    improver = GatewayImprover(gateway, agent="spec")
    base = default_tree("spec")
    reply = improver.improve("invariant", _evidence(), base)
    assert reply.tree == base
    assert reply.notes == "Nothing defensible to change."


def test_gateway_improver_repairs_a_malformed_reply_once() -> None:
    calls: list[ModelRequest] = []

    def handler(request: ModelRequest) -> str:
        calls.append(request)
        if len(calls) == 1:
            return (
                "FILE: prompts/system.md\n<<<<<<< SEARCH\nno such text\n"
                "=======\nx\n>>>>>>> REPLACE\n"
            )
        return _marker_edit(request)

    gateway = ScriptedGateway(handler)
    improver = GatewayImprover(gateway, agent="spec")
    reply = improver.improve("invariant", _evidence(), default_tree("spec"))
    assert SOLVER_MARKER in reply.tree[SYSTEM_PATH]
    assert len(calls) == 2
    assert "could not be applied" in calls[1].messages[-1].content
    assert "matched 0 times" in calls[1].messages[-1].content


def test_gateway_improver_raises_after_a_failed_repair() -> None:
    bad = "FILE: prompts/system.md\n<<<<<<< SEARCH\nnope\n=======\nx\n>>>>>>> REPLACE\n"
    gateway = ScriptedGateway(lambda request: bad)
    improver = GatewayImprover(gateway, agent="spec")
    with pytest.raises(ValueError, match="matched 0 times"):
        improver.improve("invariant", _evidence(), default_tree("spec"))
    assert len(gateway.requests) == 2


# -- Stage fault injection (real surface validator) --------------------------


def test_fault_invalid_edit_falls_back(tmp_path: Path) -> None:
    bad = "FILE: prompts/system.md\n<<<<<<< SEARCH\nghost text\n=======\nx\n>>>>>>> REPLACE\n"
    gateway = ScriptedGateway(lambda request: bad)
    stage = _spec_stage(_spec_loop(gateway, tmp_path), default_tree("spec"))
    assert stage.fell_back is True
    assert stage.tree == default_tree("spec")
    assert "matched 0 times" in stage.error


def test_fault_frozen_line_edit_rejected_then_recovers(tmp_path: Path) -> None:
    def handler(request: ModelRequest) -> str:
        prompt = request.messages[0].content
        if "Feedback on your previous attempt" in prompt:
            return _marker_edit(request)
        return (
            "Trimming a sentence.\n"
            f"FILE: {SYSTEM_PATH}\n"
            "<<<<<<< SEARCH\n"
            f"{ANCHOR}\n"
            "=======\n"
            "5. Do not wrap the response in conversational text or external greetings.\n"
            ">>>>>>> REPLACE\n"
        )

    gateway = ScriptedGateway(handler)
    stage = _spec_stage(_spec_loop(gateway, tmp_path), default_tree("spec"))
    assert stage.fell_back is False
    assert stage.attempts == 2
    assert SOLVER_MARKER in stage.tree[SYSTEM_PATH]
    assert FROZEN_LINE in stage.tree[SYSTEM_PATH]


def test_fault_over_cap_edit_falls_back(tmp_path: Path) -> None:
    filler = "x" * 25_000

    def handler(request: ModelRequest) -> str:
        return (
            "Padding the prompt.\n"
            f"FILE: {SYSTEM_PATH}\n"
            "<<<<<<< SEARCH\n"
            f"{ANCHOR}\n"
            "=======\n"
            f"{ANCHOR}\n{filler}\n"
            ">>>>>>> REPLACE\n"
        )

    stage = _spec_stage(_spec_loop(ScriptedGateway(handler), tmp_path), default_tree("spec"))
    assert stage.fell_back is True
    assert "over the tree budget" in stage.error


def test_fault_secret_edit_falls_back(tmp_path: Path) -> None:
    def handler(request: ModelRequest) -> str:
        return (
            "Recording a credential.\n"
            f"FILE: {SYSTEM_PATH}\n"
            "<<<<<<< SEARCH\n"
            f"{ANCHOR}\n"
            "=======\n"
            f"{ANCHOR}\npassword = 'sup3rsecretvalue9'\n"
            ">>>>>>> REPLACE\n"
        )

    stage = _spec_stage(_spec_loop(ScriptedGateway(handler), tmp_path), default_tree("spec"))
    assert stage.fell_back is True
    assert "secret pattern" in stage.error


def test_fault_off_surface_edit_falls_back(tmp_path: Path) -> None:
    def handler(request: ModelRequest) -> str:
        return "Adding a script.\nCREATE: scripts/run.py\n<<<<<<< FILE\nprint('x')\n>>>>>>> FILE\n"

    stage = _spec_stage(_spec_loop(ScriptedGateway(handler), tmp_path), default_tree("spec"))
    assert stage.fell_back is True
    assert "scripts, subagents and plugins are not harness" in stage.error


# -- Engine fault injection + the real improver end to end -------------------


def _fake_adapter_edit(request: ModelRequest) -> str:
    return (
        "Marking the system prompt.\n"
        f"FILE: {SYSTEM_PATH}\n"
        "<<<<<<< SEARCH\n"
        "base system\n"
        "=======\n"
        "base system marker\n"
        ">>>>>>> REPLACE\n"
    )


def test_engine_dead_rollout_with_real_improver(tmp_path: Path) -> None:
    adapter = FakeAdapter(tmp_path, die_on=frozenset({"t1-inv0"}))
    gateway = ScriptedGateway(_fake_adapter_edit)
    improver = GatewayImprover(gateway, agent="spec")
    result = run_parallel(adapter, "t1", improver=improver, options=ModeOptions(k=1))
    assert result.ledger.dead_rollouts == ["inv0"]
    assert result.finals[0].delivered


def test_engine_improver_error_falls_back_everywhere(tmp_path: Path) -> None:
    adapter = FakeAdapter(tmp_path)

    class DownGateway:
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, request: ModelRequest) -> ModelResponse:
            self.calls += 1
            raise ModelGatewayError("LLM_TIMEOUT", "gateway timed out")

    gateway = DownGateway()
    improver = GatewayImprover(gateway, agent="spec")
    result = run_parallel(adapter, "t1", improver=improver, options=ModeOptions(k=1))
    assert all(stage.fell_back for stage in result.stages)
    assert len(result.stages) == 3
    assert result.finals[0].delivered is False
    assert gateway.calls == 6


def test_engine_real_improver_adopts_the_marker(tmp_path: Path) -> None:
    adapter = SpecTaskAdapter(runs_root=tmp_path / "runs", gateway_factory=HarnessAwareGateway)
    gateway = ScriptedGateway(_marker_edit)
    improver = GatewayImprover(gateway, agent="spec")
    result = run_parallel(adapter, "calculator", improver=improver, options=ModeOptions(k=1))
    assert result.finals[0].delivered
    assert SOLVER_MARKER in result.finals[0].tree[SYSTEM_PATH]
    aggregate = next(stage for stage in result.stages if stage.label == "agg0")
    assert "marker" in aggregate.notes or SOLVER_MARKER in aggregate.tree[SYSTEM_PATH]
