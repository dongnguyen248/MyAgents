from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any

from asf.state_machine.graph import StageGraph
from asf.state_machine.triggers import Trigger
from asf.workflow.definition import DEFAULT_MAX_REVISIONS


class InvalidTransition(Exception):
    def __init__(
        self,
        stage: str,
        trigger: str,
        allowed: tuple[str, ...] = (),
    ) -> None:
        self.stage = stage
        self.trigger = trigger
        self.allowed = allowed
        super().__init__(
            f"Invalid transition from stage '{stage}' via trigger '{trigger}'. "
            f"Allowed triggers: {list(allowed)}"
        )

    def to_platform_error(self, now: datetime) -> dict[str, Any]:
        if not isinstance(now, datetime):
            raise TypeError("now must be an instance of datetime")
        if now.tzinfo is None or now.tzinfo.utcoffset(now) is None:
            raise ValueError("Timestamp must be timezone-aware (tzinfo must not be None)")

        return {
            "code": "WORKFLOW_INVALID_TRANSITION",
            "message": str(self),
            "category": "WORKFLOW",
            "retryable": False,
            "details": {
                "stage": self.stage,
                "trigger": self.trigger,
                "allowed": list(self.allowed),
            },
            "timestamp": now.isoformat(),
        }


@dataclass(frozen=True)
class RunState:
    stage: str
    revisions: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Store an immutable copy of revisions
        object.__setattr__(self, "revisions", MappingProxyType(dict(self.revisions)))

    def __deepcopy__(self, memo: dict) -> RunState:
        # MappingProxyType cannot be pickled, which is what
        # copy.deepcopy (and pydantic's model_copy(deep=True)) falls
        # back to. The state is an immutable value: a fresh RunState
        # over a plain dict of the revisions is an exact deep copy.
        return RunState(stage=self.stage, revisions=dict(self.revisions))

    @classmethod
    def initial(cls) -> RunState:
        return cls(stage="NEW", revisions={})


def allowed_triggers(graph: StageGraph, stage: str) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for edge in graph.edges:
        if edge.source == stage and edge.trigger.value not in seen:
            seen.add(edge.trigger.value)
            result.append(edge.trigger.value)
    return tuple(result)


def apply(
    graph: StageGraph,
    state: RunState,
    trigger: str | Trigger,
) -> RunState:
    stages_by_name = {s.name: s for s in graph.stages}

    # 1. Unknown stage check
    if state.stage not in stages_by_name:
        raise InvalidTransition(
            stage=state.stage,
            trigger=str(trigger),
            allowed=(),
        )

    # 2. Unknown trigger check
    try:
        trig = Trigger(trigger)
    except ValueError:
        raise InvalidTransition(
            stage=state.stage,
            trigger=str(trigger),
            allowed=allowed_triggers(graph, state.stage),
        )

    # 3. Candidate edges from current stage for this trigger
    candidates = [
        edge
        for edge in graph.edges
        if edge.source == state.stage and edge.trigger == trig
    ]
    if not candidates:
        raise InvalidTransition(
            stage=state.stage,
            trigger=trig.value,
            allowed=allowed_triggers(graph, state.stage),
        )

    # 4. Handle transitions and guard evaluations
    current_stage_info = stages_by_name[state.stage]
    step_id = current_stage_info.step_id

    if trig == Trigger.REVISE:
        if step_id is None:
            raise ValueError(f"Stage '{state.stage}' with REVISE transition must have a step_id")
        max_rev = graph.max_revisions.get(step_id, DEFAULT_MAX_REVISIONS)
        curr_rev = state.revisions.get(step_id, 0)
        if curr_rev < max_rev:
            edge = next(e for e in candidates if e.guard == "within_limit")
            new_revisions = dict(state.revisions)
            new_revisions[step_id] = curr_rev + 1
            return RunState(stage=edge.target, revisions=new_revisions)
        else:
            edge = next(e for e in candidates if e.guard == "limit_reached")
            return RunState(stage=edge.target, revisions=dict(state.revisions))

    elif trig == Trigger.RESUME:
        edge = candidates[0]
        new_revisions = dict(state.revisions)
        if step_id is not None:
            new_revisions[step_id] = 0
        return RunState(stage=edge.target, revisions=new_revisions)

    else:
        edge = candidates[0]
        return RunState(stage=edge.target, revisions=dict(state.revisions))
