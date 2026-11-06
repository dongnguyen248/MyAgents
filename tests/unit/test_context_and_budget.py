"""Context quality, test fail-fast, usage accounting and budgets.

Covers the Prompt-8 requirements: the repo map (bounded, outlines
only, never reads outside the tree), PLAN/SPEC slicing for
implement, test-command fail-fast with skipped entries, prompt
tailing of test reports, platform-side usage accumulation
(including across the in-conversation repair loop), the run
budget failing a run BEFORE another model call, step deadlines
reaching the gateway as a smaller timeout, prompt-cache hints in
gateway payloads, and the review fast path.
"""

from __future__ import annotations

from datetime import UTC, datetime
from itertools import count

from asf.agents._shared.context_slicing import slice_plan, slice_spec
from asf.agents._shared.repomap import build_repo_map
from asf.agents._shared.report_tail import tail_artifact_for_prompt, tail_text
from asf.agents.base import AgentRuntime, BaseAgent, Issue
from asf.agents.implement.agent import ImplementAgent, ImplementSettings
from asf.agents.loading import load_implement_prompts, load_review_prompts
from asf.agents.review.agent import ReviewAgent, ReviewSettings
from asf.agents.test.agent import TestAgent
from asf.contracts.models import (
    AgentMetadata,
    AgentRequest,
    Artifact,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelUsage,
)
from asf.evaluation.service import MetricsService
from asf.integrations.openai_compatible import OpenAICompatibleGateway
from asf.models.counting import CountingGateway
from asf.models.fake import ScriptedModelGateway
from asf.orchestrator.budget import RunBudget
from asf.orchestrator.engine import Orchestrator
from asf.orchestrator.registry import AgentRegistry
from asf.tools.fake import InMemoryRepository
from asf.tools.ports import CommandResult, SandboxResult
from asf.workflow.definition import WorkflowDefinition, WorkflowStepDef
from tests.unit.implement_helpers import (
    make_implement_request,
    make_plan_artifact,
    make_spec_artifact,
    make_task_artifact,
)

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


def _runtime(gateway) -> AgentRuntime:
    ids = count(1)
    return AgentRuntime(gateway, lambda: NOW, lambda: f"id-{next(ids)}")


def _response(text: str, usage: tuple[int, int], finish: str = "stop") -> ModelResponse:
    return ModelResponse(
        content=text,
        model="test-model",
        usage=ModelUsage(prompt_tokens=usage[0], completion_tokens=usage[1]),
        finish_reason=finish,
    )


# ---------------------------------------------------------------- repo map


class _SpyRepository(InMemoryRepository):
    def __init__(self) -> None:
        super().__init__()
        self.read_paths: list[str] = []

    def read_file(self, path, ref, max_bytes=256_000):  # type: ignore[override]
        self.read_paths.append(path)
        return super().read_file(path, ref, max_bytes)


def _repo() -> _SpyRepository:
    repo = _SpyRepository()
    repo.add_tree(
        "main",
        {
            "src/calculator.py": (
                "from src.util import helper\n\ndef add(a, b):\n    return helper(a + b)\n"
            ),
            "src/util.py": (
                "def helper(x):\n    secret_body_line = 'BODY-SECRET'\n"
                "    return x * 2\n\n"
                "class Greeter:\n    def greet(self):\n        return 'hi'\n"
            ),
            "src/other.py": "def unrelated():\n    return 0\n",
            "README.md": "# hi\n",
        },
    )
    return repo


def test_repo_map_outlines_neighbours_and_imports_without_bodies():
    repo = _repo()
    text = build_repo_map(
        repo,
        ref="main",
        expected_files=["src/calculator.py"],
        max_chars=6000,
    )
    assert "src/calculator.py" in text
    assert "src/util.py" in text
    # Outlines carry signatures, never bodies.
    assert "def helper(x):" in text
    assert "class Greeter:" in text
    assert "BODY-SECRET" not in text
    # Reads never left the tree listing.
    assert set(repo.read_paths) <= set(repo.list_tree("main"))


def test_repo_map_respects_the_character_limit():
    repo = _repo()
    text = build_repo_map(
        repo,
        ref="main",
        expected_files=["src/calculator.py"],
        max_chars=120,
    )
    assert len(text) <= 160  # limit + the truncation marker line
    assert "truncated" in text


def test_repo_map_empty_tree_and_disabled():
    repo = _repo()
    assert build_repo_map(repo, ref="main", expected_files=[], max_chars=0) == ""


# ------------------------------------------------------------- slicing

PLAN = """# PLAN: Demo
## Linked SPEC
SPEC spec-1 v1.
## Milestones
### M1: Setup
- Deliverables: scaffold
- Acceptance criteria: builds
- Depends on: none
### M2: Billing engine
- Deliverables: invoices
- Acceptance criteria: totals add up
- Depends on: M1
### M3: Reports
- Deliverables: pdf
- Acceptance criteria: exports
- Depends on: M2
"""


def test_slice_plan_keeps_only_the_items_milestone():
    sliced = slice_plan(PLAN, "M2")
    assert "## Linked SPEC" in sliced  # preamble kept
    assert "### M2: Billing engine" in sliced
    assert "invoices" in sliced
    assert "### M1: Setup" not in sliced
    assert "scaffold" not in sliced
    assert "### M3" not in sliced
    assert "M3 — Reports" in sliced  # other milestones indexed
    assert slice_plan(PLAN, "M9") == PLAN  # unknown ref: no slicing
    assert slice_plan(PLAN, None) == PLAN


SPEC_HEAD = "# SPEC: Demo\n## Background\n"
LONG_SPEC = (
    SPEC_HEAD
    + "word " * 100
    + "\n## Billing rules\n"
    + ("invoice totals must match the ledger. " * 200)
    + "\n## Weather module\n"
    + ("sunshine and rain forecasts. " * 200)
)


def test_slice_spec_long_keeps_relevant_sections_only():
    sliced = slice_spec(
        LONG_SPEC,
        task_title="Billing invoices",
        task_description="Compute invoice totals for the ledger",
    )
    assert "## Billing rules" in sliced
    assert "## Weather module" not in sliced
    short = "# SPEC: tiny\n## A\nshort body"
    assert slice_spec(short, task_title="x", task_description="y") == short


# ------------------------------------------------- implement prompt wiring


def test_implement_prompt_carries_repo_map_and_stable_prefix():
    repo = _repo()
    gateway = ScriptedModelGateway(
        [
            '{"changes": [{"path": "src/calculator.py", "operation": "modify",'
            ' "content": "x = 1\\n"}]}',
        ]
    )
    agent = ImplementAgent(
        _runtime(gateway),
        repo,
        ImplementSettings(
            prompts=load_implement_prompts(),
            edit_format="json",
            repair_attempts=0,
        ),
    )
    result = agent.execute(
        make_implement_request(
            expected_files=["src/calculator.py"],
        )
    )
    assert result.status == "SUCCESS"
    request = gateway.requests[0]
    joined = "\n".join(m.content for m in request.messages)
    assert "<<<REPO MAP>>>" in joined
    assert "Outlines of neighbouring files" in joined
    # Stable prefix = system + the SPEC/PLAN message.
    assert request.metadata["cachePrefixMessages"] == 2
    assert "<<<SPEC>>>" in request.messages[1].content
    assert "<<<TASK ITEM>>>" in request.messages[2].content


# ------------------------------------------------------------- fail-fast


class _ScriptedSandbox:
    """Sandbox double: per-argv exit codes, honours the port contract."""

    def __init__(self, exits: dict[tuple[str, ...], int]) -> None:
        self._exits = exits
        self.ran: list[tuple[str, ...]] = []
        self.seen_fail_fast: bool | None = None

    def run(self, commands, changes, ref, *, fail_fast=True):  # type: ignore[no-untyped-def]
        self.seen_fail_fast = fail_fast
        outcomes: list[CommandResult] = []
        failed = False
        for spec in commands:
            if failed and fail_fast:
                outcomes.append(
                    CommandResult(
                        exit_code=-1,
                        stdout="",
                        stderr="",
                        duration_ms=0,
                        skipped=True,
                    )
                )
                continue
            self.ran.append(tuple(spec.argv))
            code = self._exits.get(tuple(spec.argv), 0)
            outcomes.append(
                CommandResult(
                    exit_code=code,
                    stdout="out",
                    stderr="",
                    duration_ms=1,
                )
            )
            failed = failed or code != 0
        return SandboxResult(commands=tuple(outcomes))


def _test_request(commands: list[list[str]]) -> AgentRequest:
    code = Artifact(
        id="code-1",
        type="CODE",
        name="CODE.json",
        version="1",
        content={
            "format": "json",
            "changeSet": {
                "changes": [
                    {"path": "src/calculator.py", "operation": "create", "content": "x=1"},
                ]
            },
            "text": "code",
        },
        created_by="agent-implement",
        created_at=NOW,
        metadata={
            "specArtifactId": "spec-1",
            "specVersion": "1",
            "planArtifactId": "plan-1",
            "planVersion": "1",
            "taskArtifactId": "task-1",
            "taskVersion": "1",
            "taskItemId": "T1",
            "baseRef": "main",
        },
    )
    task = make_task_artifact()
    return AgentRequest(
        request_id="req-test",
        task_id="task-1",
        project_id="project-1",
        workflow_id="software-development",
        agent_id="agent-test",
        input={"taskItemId": "T1"},
        context={"project": {"testCommands": commands}},
        artifacts=[task, code],
        metadata={"attempt": 1},
    )


def test_test_agent_fail_fast_marks_remaining_commands_skipped():
    sandbox = _ScriptedSandbox({("pytest", "-q"): 1})
    agent = TestAgent(_runtime(ScriptedModelGateway([])), sandbox)
    result = agent.execute(
        _test_request(
            [["pytest", "-q"], ["lint"], ["build"]],
        )
    )
    assert result.status == "SUCCESS"
    report = result.output
    assert report["verdict"] == "FAIL"
    assert report["commands"][0]["exitCode"] == 1
    assert report["commands"][1]["skipped"] is True
    assert report["commands"][1]["exitCode"] is None
    assert report["commands"][2]["skipped"] is True
    assert "(2 skipped)" in report["summary"]
    assert sandbox.ran == [("pytest", "-q")]  # later commands never ran
    artifact = result.artifacts[0]
    assert artifact.content["report"]["commands"][2]["skipped"] is True


def test_test_agent_fail_fast_disabled_runs_everything():
    sandbox = _ScriptedSandbox({("pytest", "-q"): 1})
    agent = TestAgent(
        _runtime(ScriptedModelGateway([])),
        sandbox,
        fail_fast=False,
    )
    result = agent.execute(_test_request([["pytest", "-q"], ["lint"]]))
    report = result.output
    assert sandbox.ran == [("pytest", "-q"), ("lint",)]
    assert "skipped" not in report["commands"][1]
    assert report["summary"] == "FAIL: 1/2 commands passed"


# ------------------------------------------------------------ report tails


def test_tail_text_keeps_error_lines_and_the_tail():
    lines = [f"line {i}" for i in range(300)]
    lines[10] = "AssertionError: totals differ"
    text = tail_text("\n".join(lines), max_lines=20)
    assert "AssertionError: totals differ" in text
    assert "line 299" in text
    assert "line 100" not in text
    assert "omitted" in text


def test_tail_artifact_for_prompt_shrinks_streams_only():
    artifact = {
        "id": "r1",
        "type": "TEST_REPORT",
        "version": "1",
        "content": {
            "format": "json",
            "report": {
                "verdict": "FAIL",
                "commands": [
                    {
                        "argv": ["pytest"],
                        "exitCode": 1,
                        "stdout": "\n".join(f"o{i}" for i in range(500)),
                        "stderr": "Traceback: boom",
                    }
                ],
            },
        },
    }
    trimmed = tail_artifact_for_prompt(artifact, max_lines=10)
    assert len(trimmed["content"]["report"]["commands"][0]["stdout"]) < 500
    # The source artifact (the stored evidence) is untouched.
    assert len(artifact["content"]["report"]["commands"][0]["stdout"]) > 1000


# -------------------------------------------------------- usage accounting


def test_usage_lands_in_result_metrics_and_metrics_service():
    gateway = ScriptedModelGateway([_response("done", usage=(11, 7))])

    class _Caller(BaseAgent):
        @property
        def metadata(self) -> AgentMetadata:  # type: ignore[override]
            return AgentMetadata(
                id="agent-spec",
                name="Spec",
                type="spec",
                version="1",
                status="IDLE",
                capabilities=[],
                configuration={},
            )

        def _check(self, request: AgentRequest) -> list[Issue]:
            return []

        def _run(self, request: AgentRequest):  # type: ignore[no-untyped-def]
            self._runtime.models.complete(
                ModelRequest(
                    messages=[
                        ModelMessage(role="user", content="hi"),
                    ]
                )
            )
            return {}, []

    agent = _Caller(_runtime(gateway))
    request = AgentRequest(
        request_id="r1",
        task_id="t1",
        project_id="p1",
        workflow_id="w",
        agent_id="agent-spec",
        input={},
        context={},
        artifacts=[],
    )
    result = agent.execute(request)
    assert result.metrics.model_calls == 1
    assert result.metrics.prompt_tokens == 11
    assert result.metrics.completion_tokens == 7

    service = MetricsService(clock=lambda: NOW)
    service.record("agent-spec", result, run_id="run-9")
    metrics = service.agent_metrics("agent-spec")
    assert metrics["promptTokens"] == 11
    assert metrics["completionTokens"] == 7
    assert metrics["modelCalls"] == 1
    assert service.run_metrics("run-9")["promptTokens"] == 11


def test_usage_sums_across_the_repair_loop():
    bad = "FILE: src/nope.py\n<<<<<<< SEARCH\nx\n=======\ny\n>>>>>>> REPLACE\n"
    good = "CREATE: src/calculator.py\n<<<<<<< FILE\nx = 1\n>>>>>>> FILE\n"
    gateway = ScriptedModelGateway(
        [
            _response(bad, usage=(10, 5)),
            _response(good, usage=(20, 7)),
        ]
    )
    repo = InMemoryRepository()
    agent = ImplementAgent(
        _runtime(gateway), repo, ImplementSettings(prompts=load_implement_prompts())
    )
    result = agent.execute(make_implement_request())
    assert result.status == "SUCCESS"
    assert result.output["repairs"] == 1
    # The RESULT metrics (platform-counted) sum both calls, exactly
    # like the agent output's own usage report.
    assert result.metrics.model_calls == 2
    assert result.metrics.prompt_tokens == 30
    assert result.metrics.completion_tokens == 12


# ------------------------------------------------------------------ budget


class _StepAgent(BaseAgent):
    def __init__(self, runtime: AgentRuntime, agent_id: str, type_: str) -> None:
        super().__init__(runtime)
        self._meta = AgentMetadata(
            id=agent_id,
            name=agent_id,
            type=type_,
            version="1",
            status="IDLE",
            capabilities=[],
            configuration={},
        )

    @property
    def metadata(self) -> AgentMetadata:
        return self._meta

    def _check(self, request: AgentRequest) -> list[Issue]:
        return []

    def _run(self, request: AgentRequest):  # type: ignore[no-untyped-def]
        self._runtime.models.complete(
            ModelRequest(
                messages=[
                    ModelMessage(role="user", content="go"),
                ]
            )
        )
        artifact = Artifact(
            id=f"art-{self._meta.type}",
            type=self._meta.type.upper(),
            name="out",
            version="1",
            content={"text": "ok"},
            created_by=self._meta.id,
            created_at=NOW,
            metadata={},
        )
        return {}, [artifact]


def _budget_engine(budget: RunBudget, gateway: ScriptedModelGateway) -> Orchestrator:
    registry = AgentRegistry()
    ids = count(1)
    runtime = AgentRuntime(gateway, lambda: NOW, lambda: f"id-{next(ids)}")
    registry.register(_StepAgent(runtime, "agent-spec", "spec"))
    registry.register(_StepAgent(runtime, "agent-plan", "plan"))
    definition = WorkflowDefinition(
        id="wf",
        name="wf",
        version="1",
        steps=[
            WorkflowStepDef(
                id="spec",
                name="Spec",
                type="AGENT",
                stage="SPEC",
                requires_approval=False,
                agent_type="spec",
                produces=["SPEC"],
            ),
            WorkflowStepDef(
                id="plan",
                name="Plan",
                type="AGENT",
                stage="PLAN",
                requires_approval=False,
                agent_type="plan",
                produces=["PLAN"],
            ),
        ],
    )
    return Orchestrator(
        definition,
        registry,
        clock=lambda: NOW,
        new_id=lambda: f"run-{next(ids)}",
        budget=budget,
    )


def test_budget_exceeded_fails_run_before_another_model_call():
    gateway = ScriptedModelGateway(
        [
            _response("a", usage=(10, 5)),
            _response("b", usage=(10, 5)),
            _response("c", usage=(10, 5)),
        ]
    )
    engine = _budget_engine(RunBudget(max_model_calls=1), gateway)
    run = engine.start(
        task_id="t1",
        project_id="p1",
        inputs={"spec": {}, "plan": {}},
        context={},
    )
    run = engine.tick(run.id)  # spec runs: 1 call used (not > 1 yet)
    assert run.state.stage == "PLAN"
    run = engine.tick(run.id)  # plan dispatch still allowed at exactly 1
    assert run.state.stage == "COMPLETED"
    assert len(gateway.requests) == 2

    gateway2 = ScriptedModelGateway(
        [
            _response("a", usage=(10, 5)),
            _response("b", usage=(10, 5)),
        ]
    )
    engine2 = _budget_engine(RunBudget(max_prompt_tokens=5), gateway2)
    run = engine2.start(
        task_id="t1",
        project_id="p1",
        inputs={"spec": {}, "plan": {}},
        context={},
    )
    run = engine2.tick(run.id)  # spec consumes 10 prompt tokens
    run = engine2.tick(run.id)  # 10 > 5: plan never dispatches
    assert run.state.stage == "FAILED"
    assert run.errors[-1].code == "RUN_BUDGET_EXCEEDED"
    assert run.errors[-1].retryable is False
    assert len(gateway2.requests) == 1  # the model was NOT called again


# ---------------------------------------------------------------- deadline


def test_counting_gateway_injects_remaining_deadline():
    inner = ScriptedModelGateway([_response("ok", usage=(1, 1))])
    gateway = CountingGateway(inner)
    ticks = iter([NOW, NOW])  # tracker start + execute stamps
    clock = lambda: next(ticks, NOW)  # noqa: E731
    agent = _StepAgent(
        AgentRuntime(gateway, clock, lambda: "id-1"),
        "agent-spec",
        "spec",
    )
    import datetime as _dt

    later = NOW + _dt.timedelta(seconds=12)
    agent._runtime = AgentRuntime(
        gateway,
        lambda: later,
        lambda: "id-1",
    )
    request = AgentRequest(
        request_id="r1",
        task_id="t1",
        project_id="p1",
        workflow_id="w",
        agent_id="agent-spec",
        input={},
        context={},
        artifacts=[],
        metadata={"stepTimeoutSeconds": 30},
    )
    # Start the execution at NOW by using the tracked path with a
    # clock that starts at NOW and then jumps: execute reads
    # t_start from the runtime clock — rebuild it for the sequence.
    stamps = iter([NOW, later, later])
    agent._runtime = AgentRuntime(
        gateway,
        lambda: next(stamps, later),
        lambda: "id-1",
    )
    result = agent.execute(request)
    assert result.status == "SUCCESS"
    deadline = inner.requests[0].metadata["deadlineSeconds"]
    assert 17.0 < deadline < 19.0  # 30s budget - 12s elapsed


def test_gateway_uses_the_smaller_deadline_timeout():
    seen: dict[str, float] = {}

    class _Transport:
        def post(self, url, *, headers, body, timeout_seconds, **kwargs):  # type: ignore[no-untyped-def]
            seen["timeout"] = timeout_seconds
            return (
                200,
                {},
                (
                    b'{"model": "m", "choices": [{"message": {"content": "ok"},'
                    b' "finish_reason": "stop"}], "usage":'
                    b' {"prompt_tokens": 1, "completion_tokens": 1}}'
                ),
            )

    gateway = OpenAICompatibleGateway(
        base_url="https://example.test/v1",
        model="m",
        api_key="k",
        transport=_Transport(),
        timeout_seconds=300.0,
    )
    gateway.complete(
        ModelRequest(
            messages=[ModelMessage(role="user", content="hi")],
            metadata={"deadlineSeconds": 7},
        )
    )
    assert seen["timeout"] == 7
    gateway.complete(
        ModelRequest(
            messages=[ModelMessage(role="user", content="hi")],
            metadata={},
        )
    )
    assert seen["timeout"] == 300.0


def test_gateway_cache_control_only_with_prompt_cache_enabled():
    bodies: list[bytes] = []

    class _Transport:
        def post(self, url, *, headers, body, timeout_seconds, **kwargs):  # type: ignore[no-untyped-def]
            bodies.append(body)
            return (
                200,
                {},
                (
                    b'{"model": "m", "choices": [{"message": {"content": "ok"},'
                    b' "finish_reason": "stop"}], "usage":'
                    b' {"prompt_tokens": 1, "completion_tokens": 1}}'
                ),
            )

    import json as _json

    messages = [
        ModelMessage(role="system", content="sys"),
        ModelMessage(role="user", content="stable"),
        ModelMessage(role="user", content="changing"),
    ]
    cached = OpenAICompatibleGateway(
        base_url="https://api.anthropic.com/v1",
        model="m",
        api_key="k",
        transport=_Transport(),
        prompt_cache=True,
    )
    cached.complete(
        ModelRequest(
            messages=messages,
            metadata={"cachePrefixMessages": 2},
        )
    )
    payload = _json.loads(bodies[-1])
    assert payload["messages"][0]["content"][0]["cache_control"] == {
        "type": "ephemeral",
    }
    assert payload["messages"][1]["content"][0]["text"] == "stable"
    assert payload["messages"][2]["content"] == "changing"

    plain = OpenAICompatibleGateway(
        base_url="https://example.test/v1",
        model="m",
        api_key="k",
        transport=_Transport(),
    )
    plain.complete(
        ModelRequest(
            messages=messages,
            metadata={"cachePrefixMessages": 2},
        )
    )
    payload = _json.loads(bodies[-1])
    assert payload["messages"][0]["content"] == "sys"


# ------------------------------------------------------------ review skip


def _review_request(*, verdict: str = "PASS") -> AgentRequest:
    code_changes = {
        "changes": [
            {"path": "src/calculator.py", "operation": "create", "content": "x = 1\n"},
        ]
    }
    code = Artifact(
        id="code-1",
        type="CODE",
        name="CODE.json",
        version="1",
        content={"format": "json", "changeSet": code_changes, "text": "code"},
        created_by="agent-implement",
        created_at=NOW,
        metadata={
            "specArtifactId": "spec-1",
            "specVersion": "1",
            "planArtifactId": "plan-1",
            "planVersion": "1",
            "taskArtifactId": "task-1",
            "taskVersion": "1",
            "taskItemId": "T1",
            "baseRef": "main",
        },
    )
    report = Artifact(
        id="rep-1",
        type="TEST_REPORT",
        name="Test report",
        version="1",
        content={
            "format": "json",
            "report": {
                "verdict": verdict,
                "commands": [],
                "summary": f"{verdict}: ok",
            },
            "text": verdict,
        },
        created_by="agent-test",
        created_at=NOW,
        metadata={"codeArtifactId": "code-1", "codeVersion": "1", "taskItemId": "T1"},
    )
    return AgentRequest(
        request_id="req-review",
        task_id="task-1",
        project_id="project-1",
        workflow_id="software-development",
        agent_id="agent-review",
        input={"taskItemId": "T1"},
        context={"project": {}},
        artifacts=[
            make_spec_artifact(),
            make_plan_artifact(),
            make_task_artifact(),
            code,
            report,
        ],
        metadata={"attempt": 1},
    )


def test_review_skips_llm_when_tests_pass_and_diff_small():
    gateway = ScriptedModelGateway([])
    agent = ReviewAgent(
        _runtime(gateway),
        ReviewSettings(
            prompts=load_review_prompts(),
            skip_when_tests_pass=True,
            max_diff_lines=200,
        ),
    )
    result = agent.execute(_review_request())
    assert result.status == "SUCCESS"
    assert result.output["verdict"] == "APPROVE"
    assert result.output["skipped"] is True
    assert gateway.requests == []  # no model call at all
    assert result.artifacts[0].type == "CODE_REVIEW"


def test_review_does_not_skip_when_tests_failed():
    gateway = ScriptedModelGateway(
        [
            '{"findings": [], "verdict": "APPROVE"}',
        ]
    )
    agent = ReviewAgent(
        _runtime(gateway),
        ReviewSettings(
            prompts=load_review_prompts(),
            skip_when_tests_pass=True,
            max_diff_lines=200,
        ),
    )
    result = agent.execute(_review_request(verdict="FAIL"))
    assert result.status == "SUCCESS"
    assert "skipped" not in (result.output or {})
    assert len(gateway.requests) == 1
