from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from asf.state_machine.triggers import StageKind, Trigger
from asf.workflow.definition import (
    DEFAULT_MAX_REVISIONS,
    WorkflowDefinition,
    WorkflowStepDef,
)

Guard = Literal["none", "within_limit", "limit_reached"]


@dataclass(frozen=True)
class StageInfo:
    name: str
    kind: StageKind
    step_id: str | None = None


@dataclass(frozen=True)
class Edge:
    source: str
    trigger: Trigger
    target: str
    guard: Guard = "none"


@dataclass(frozen=True)
class StageGraph:
    stages: tuple[StageInfo, ...]
    edges: tuple[Edge, ...]
    max_revisions: Mapping[str, int]


def _entry_stage_name(step: WorkflowStepDef) -> str:
    if step.requires_approval:
        return f"{step.stage}_DRAFT"
    return step.stage


def build_graph(definition: WorkflowDefinition) -> StageGraph:
    stages: list[StageInfo] = [StageInfo(name="NEW", kind=StageKind.INITIAL, step_id=None)]
    max_revisions: dict[str, int] = {}

    for step in definition.steps:
        if step.requires_approval:
            s_name = step.stage
            stages.append(StageInfo(name=f"{s_name}_DRAFT", kind=StageKind.DRAFT, step_id=step.id))
            stages.append(
                StageInfo(name=f"{s_name}_REVIEW", kind=StageKind.REVIEW, step_id=step.id)
            )
            stages.append(
                StageInfo(name=f"{s_name}_REJECTED", kind=StageKind.REJECTED, step_id=step.id)
            )
            stages.append(
                StageInfo(name=f"{s_name}_APPROVED", kind=StageKind.APPROVED, step_id=step.id)
            )
            stages.append(
                StageInfo(name=f"{s_name}_ESCALATED", kind=StageKind.ESCALATED, step_id=step.id)
            )
            max_revisions[step.id] = (
                step.max_revisions if step.max_revisions is not None else DEFAULT_MAX_REVISIONS
            )
        else:
            stages.append(StageInfo(name=step.stage, kind=StageKind.STEP, step_id=step.id))

    stages.append(StageInfo(name="COMPLETED", kind=StageKind.COMPLETED, step_id=None))
    stages.append(StageInfo(name="FAILED", kind=StageKind.FAILED, step_id=None))
    stages.append(StageInfo(name="CANCELLED", kind=StageKind.CANCELLED, step_id=None))

    edges: list[Edge] = []
    steps = definition.steps

    # 1. NEW --START--> entry(first step)
    edges.append(Edge(source="NEW", trigger=Trigger.START, target=_entry_stage_name(steps[0])))

    # 2. Step transitions
    num_steps = len(steps)
    for i, step in enumerate(steps):
        next_target = _entry_stage_name(steps[i + 1]) if i + 1 < num_steps else "COMPLETED"
        if step.requires_approval:
            s_name = step.stage
            draft = f"{s_name}_DRAFT"
            review = f"{s_name}_REVIEW"
            rejected = f"{s_name}_REJECTED"
            approved = f"{s_name}_APPROVED"
            escalated = f"{s_name}_ESCALATED"

            # S_DRAFT --COMPLETE--> S_REVIEW
            edges.append(Edge(source=draft, trigger=Trigger.COMPLETE, target=review))

            # S_REVIEW --APPROVED--> S_APPROVED
            edges.append(Edge(source=review, trigger=Trigger.APPROVED, target=approved))

            # S_REVIEW --REJECTED--> S_REJECTED
            edges.append(Edge(source=review, trigger=Trigger.REJECTED, target=rejected))

            # S_REVIEW --REQUEST_CHANGES--> S_REJECTED
            edges.append(Edge(source=review, trigger=Trigger.REQUEST_CHANGES, target=rejected))

            # S_REJECTED --REVISE--> S_DRAFT (guard within_limit)
            edges.append(
                Edge(
                    source=rejected,
                    trigger=Trigger.REVISE,
                    target=draft,
                    guard="within_limit",
                )
            )

            # S_REJECTED --REVISE--> S_ESCALATED (guard limit_reached)
            edges.append(
                Edge(
                    source=rejected,
                    trigger=Trigger.REVISE,
                    target=escalated,
                    guard="limit_reached",
                )
            )

            # S_ESCALATED --RESUME--> S_DRAFT
            edges.append(Edge(source=escalated, trigger=Trigger.RESUME, target=draft))

            # S_APPROVED --ADVANCE--> entry(next step)
            edges.append(Edge(source=approved, trigger=Trigger.ADVANCE, target=next_target))
        else:
            # plain step: S --COMPLETE--> entry(next step)
            edges.append(Edge(source=step.stage, trigger=Trigger.COMPLETE, target=next_target))

    # 3. Every non-terminal stage --FAIL--> FAILED and --CANCEL--> CANCELLED
    terminal_stages = {"COMPLETED", "FAILED", "CANCELLED"}
    for stage_info in stages:
        if stage_info.name not in terminal_stages:
            edges.append(Edge(source=stage_info.name, trigger=Trigger.FAIL, target="FAILED"))
            edges.append(Edge(source=stage_info.name, trigger=Trigger.CANCEL, target="CANCELLED"))

    return StageGraph(
        stages=tuple(stages),
        edges=tuple(edges),
        max_revisions=max_revisions,
    )
