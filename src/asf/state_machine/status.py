from __future__ import annotations

from asf.state_machine.graph import StageGraph
from asf.state_machine.triggers import StageKind

_TASK_STATUS_BY_KIND: dict[StageKind, str] = {
    StageKind.INITIAL: "NEW",
    StageKind.DRAFT: "IN_PROGRESS",
    StageKind.REVIEW: "WAITING",
    StageKind.REJECTED: "IN_PROGRESS",
    StageKind.APPROVED: "IN_PROGRESS",
    StageKind.ESCALATED: "WAITING",
    StageKind.STEP: "IN_PROGRESS",
    StageKind.COMPLETED: "COMPLETED",
    StageKind.FAILED: "FAILED",
    StageKind.CANCELLED: "CANCELLED",
}

_RUN_STATUS_BY_KIND: dict[StageKind, str] = {
    StageKind.INITIAL: "PENDING",
    StageKind.DRAFT: "RUNNING",
    StageKind.REVIEW: "WAITING",
    StageKind.REJECTED: "RUNNING",
    StageKind.APPROVED: "RUNNING",
    StageKind.ESCALATED: "WAITING",
    StageKind.STEP: "RUNNING",
    StageKind.COMPLETED: "COMPLETED",
    StageKind.FAILED: "FAILED",
    StageKind.CANCELLED: "CANCELLED",
}


def kind_of(graph: StageGraph, stage: str) -> StageKind:
    for stage_info in graph.stages:
        if stage_info.name == stage:
            return stage_info.kind
    raise KeyError(f"Stage '{stage}' not found in graph")


def task_status(graph: StageGraph, stage: str) -> str:
    kind = kind_of(graph, stage)
    return _TASK_STATUS_BY_KIND[kind]


def run_status(graph: StageGraph, stage: str) -> str:
    kind = kind_of(graph, stage)
    return _RUN_STATUS_BY_KIND[kind]
