"""The offline, harness-sensitive demo (design D7).

`HarnessAwareGateway` computes the solver's reply from the request:
the reply is missing its last required section — a defect the agent
rejects — unless the assembled system prompt carries the marker
line. `ScriptedMarkerImprover` proposes exactly the edit that adds
the marker, expressed as a SEARCH/REPLACE block and applied through
the real edit-block parser. The demo therefore shows a genuine
adopted improvement end to end with no credentials: base rollouts
fail, probed candidates pass, the composition is delivered.

This is verified plumbing, not a quality claim (design D8).
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from asf.contracts.models import ModelRequest, ModelResponse, ModelUsage
from asf.tools.edit_blocks import parse_edit_blocks
from harness.harness2.adapters import PlanTaskAdapter, SpecTaskAdapter
from harness.harness2.context import EvidenceBundle
from harness.harness2.recursion import FinalCandidate, ModeResult, run_parallel, run_sequential
from harness.harness2.surface import SYSTEM_PATH, Tree, diff_summary

__all__ = [
    "SOLVER_MARKER",
    "DemoOptions",
    "DemoResult",
    "HarnessAwareGateway",
    "ScriptedMarkerImprover",
    "run_demo",
]

SOLVER_MARKER = "Harness marker: complete-output"


def _template_headings(user_text: str) -> list[str]:
    start = user_text.index("## Template\n") + len("## Template\n")
    segment = user_text[start:]
    for suffix in ("\n## Previous specification", "\n## Reviewer feedback"):
        if suffix in segment:
            segment = segment[: segment.index(suffix)]
    return [line for line in segment.splitlines() if line.startswith("## ")]


def _linked_spec(user_text: str) -> tuple[str, str]:
    spec_id, version = "spec-1", "1"
    for line in user_text.splitlines():
        if line.startswith("ID:"):
            spec_id = line[3:].strip()
        if line.startswith("Version:"):
            version = line[8:].strip()
    return spec_id, version


def _spec_reply(user_text: str, complete_output: bool) -> str:
    headings = _template_headings(user_text)
    if not complete_output:
        headings = headings[:-1]
    blocks = ["# SPEC: Harness demo", ""]
    for heading in headings:
        blocks.append(heading)
        blocks.append("Generated content.")
        blocks.append("")
    return "\n".join(blocks)


def _plan_section(heading: str, spec_id: str, version: str) -> list[str]:
    if heading == "## Linked SPEC":
        return [heading, f"ID: {spec_id}", f"Version: {version}", ""]
    if heading == "## Milestones":
        return [
            heading,
            "### M1: Implementation",
            "- Deliverables: The module described by the SPEC",
            "- Acceptance criteria: All SPEC acceptance criteria pass",
            "- Depends on: none",
            "",
        ]
    return [heading, "Generated content.", ""]


def _plan_reply(user_text: str, complete_output: bool) -> str:
    headings = _template_headings(user_text)
    if not complete_output:
        headings = headings[:-1]
    spec_id, version = _linked_spec(user_text)
    blocks = ["# PLAN: Harness demo", ""]
    for heading in headings:
        blocks.extend(_plan_section(heading, spec_id, version))
    return "\n".join(blocks)


class HarnessAwareGateway:
    """Request-aware fake gateway: the reply depends on the harness."""

    def complete(self, request: ModelRequest) -> ModelResponse:
        system = request.messages[0].content if request.messages else ""
        user = request.messages[-1].content if request.messages else ""
        complete_output = SOLVER_MARKER in system
        agent_id = (request.metadata or {}).get("agentId", "")
        if agent_id == "agent-plan":
            content = _plan_reply(user, complete_output)
        else:
            content = _spec_reply(user, complete_output)
        return ModelResponse(
            content=content,
            model=request.model or "harness-aware",
            usage=ModelUsage(
                prompt_tokens=sum(len(m.content.split()) for m in request.messages),
                completion_tokens=len(content.split()),
            ),
            finish_reason="stop",
            metadata={},
        )


class ScriptedMarkerImprover:
    """Scripted improver: adds the solver marker line to system.md."""

    def improve(self, mission: str, evidence: EvidenceBundle, harness: Tree) -> Tree:
        tree = dict(harness)
        system = tree.get(SYSTEM_PATH, "")
        if SOLVER_MARKER in system:
            return tree
        anchor = next(line for line in reversed(system.splitlines()) if line.strip())
        reply = (
            f"FILE: {SYSTEM_PATH}\n"
            "<<<<<<< SEARCH\n"
            f"{anchor}\n"
            "=======\n"
            f"{anchor}\n"
            f"{SOLVER_MARKER}\n"
            ">>>>>>> REPLACE\n"
        )
        changeset = parse_edit_blocks(reply, existing_files=tree, expected_files={SYSTEM_PATH})
        for change in changeset.changes:
            if change.operation == "delete":
                tree.pop(change.path, None)
            else:
                tree[change.path] = change.content or ""
        return tree


@dataclass(frozen=True)
class DemoOptions:
    mode: str = "parallel"
    k: int = 1
    agent: str = "spec"
    task_id: str = "calculator"
    runs_root: Path | None = None


@dataclass(frozen=True)
class DemoResult:
    run: ModeResult
    adopted: FinalCandidate | None
    adopted_diff: list[str]


def run_demo(options: DemoOptions) -> DemoResult:
    """Run the full Parallel/Sequential structure against the fake solver."""
    root = options.runs_root or Path(tempfile.mkdtemp(prefix="harness2-demo-"))
    adapter_type = PlanTaskAdapter if options.agent == "plan" else SpecTaskAdapter
    adapter = adapter_type(runs_root=root, gateway_factory=HarnessAwareGateway)
    improver = ScriptedMarkerImprover()
    if options.mode == "sequential":
        result = run_sequential(adapter, options.task_id, k=options.k, improver=improver)
    else:
        result = run_parallel(adapter, options.task_id, k=options.k, improver=improver)
    adopted = next((final for final in result.finals if final.delivered), None)
    diff = diff_summary(adapter.base_harness(), adopted.tree) if adopted else []
    return DemoResult(run=result, adopted=adopted, adopted_diff=diff)
