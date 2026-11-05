from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    field_serializer,
    field_validator,
)

from asf.approval.models import ApprovalFeedback, ApprovalSpec
from asf.contracts.models import ActivityEvent, AgentResult, Artifact, PlatformError
from asf.state_machine.machine import RunState


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    event: ActivityEvent | None = None
    result: AgentResult | None = None
    delivered: bool = False


class WorkflowExecution(BaseModel):
    """Serializable execution checkpoint; public access always returns a copy."""

    model_config = ConfigDict(extra="forbid")

    id: str
    task_id: str
    project_id: str
    state: RunState
    inputs: dict[str, dict[str, Any]] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    artifacts: dict[str, Artifact] = Field(default_factory=dict)
    results: list[AgentResult] = Field(default_factory=list)
    errors: list[PlatformError] = Field(default_factory=list)
    feedback: list[ApprovalFeedback] = Field(default_factory=list)
    attempts: dict[str, int] = Field(default_factory=dict)
    approval_id: str | None = None
    definition: dict[str, Any] = Field(default_factory=dict)
    settings: dict[str, Any] = Field(default_factory=dict)
    started_at: AwareDatetime
    updated_at: AwareDatetime
    retry_at: AwareDatetime | None = None
    retry_attempts: int = 0
    in_flight: str | None = None
    task_order: list[str] = Field(default_factory=list)
    item_index: int = 0
    item_results: dict[str, dict[str, Artifact]] = Field(default_factory=dict)
    artifact_history: dict[str, Artifact] = Field(default_factory=dict)
    observations: list[Observation] = Field(default_factory=list)
    recovery_notes: list[str] = Field(default_factory=list)
    # Store-managed optimistic-locking counter: the version of the
    # stored row this copy was read from. Internal bookkeeping only —
    # the stores stamp it from their version column on every read and
    # guard every save with it; it is not part of any public contract.
    version: int = 0

    # Transient dispatch state, never serialized: an approval the
    # commit phase still has to request (see Orchestrator.tick). Set
    # while a result is applied to a claimed working copy; the commit
    # creates the request inside its transaction and clears this.
    _pending_approval: ApprovalSpec | None = PrivateAttr(default=None)

    @field_validator("state", mode="before")
    @classmethod
    def parse_state(cls, value: Any) -> RunState:
        if isinstance(value, RunState):
            return value
        if isinstance(value, dict):
            return RunState(stage=value["stage"], revisions=value["revisions"])
        raise ValueError("Invalid run state")

    @field_serializer("state")
    def serialize_state(self, value: RunState) -> dict[str, Any]:
        return {"stage": value.stage, "revisions": dict(value.revisions)}

    def snapshot(self) -> WorkflowExecution:
        return WorkflowExecution.model_validate_json(self.model_dump_json())

    def workflow_run(self, status: str, workflow_id: str, version: str) -> dict[str, Any]:
        return {
            "id": self.id, "workflowId": workflow_id, "workflowVersion": version,
            "projectId": self.project_id, "taskId": self.task_id, "status": status,
            "stage": self.state.stage, "revisions": dict(self.state.revisions),
            "startedAt": self.started_at.isoformat(), "updatedAt": self.updated_at.isoformat(),
            "metadata": {
                "retryAt": self.retry_at.isoformat() if self.retry_at else None,
                "inFlight": self.in_flight, "taskOrder": list(self.task_order),
                "completedItems": list(self.item_results),
            },
        }

    def touch(self, now: datetime) -> None:
        self.updated_at = now
