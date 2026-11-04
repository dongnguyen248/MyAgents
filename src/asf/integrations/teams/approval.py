from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field

from asf.approval.errors import ApprovalError
from asf.approval.models import ApprovalRequest
from asf.configuration.platform import ConfigModel
from asf.integrations.teams.config import TeamsConfig
from asf.orchestrator import Orchestrator
from asf.orchestrator.execution import WorkflowExecution


class TeamsAction(ConfigModel):
    run_id: str = Field(min_length=1, max_length=200)
    approval_id: str = Field(min_length=1, max_length=200)
    decision: Literal["APPROVED", "REJECTED", "REQUEST_CHANGES"]
    comment: str = Field(default="", max_length=4000)


class TeamsActor(ConfigModel):
    """Flow attestation: responder ID from the connector, never a card text input."""

    tenant_id: UUID
    team_id: UUID
    channel_id: str
    object_id: UUID


class TeamsApprovals:
    def __init__(self, config: TeamsConfig, engine: Orchestrator) -> None:
        self.config = config
        self.engine = engine

    def authorize(self, actor: TeamsActor) -> str:
        config = self.config
        if (
            actor.tenant_id != config.tenant_id
            or actor.team_id != config.team_id
            or actor.channel_id != config.channel_id
            or actor.object_id not in config.reviewers
        ):
            raise ApprovalError(
                "APPROVAL_NOT_AUTHORIZED", "Teams actor or channel is not authorized",
            )
        return config.reviewers[actor.object_id]

    def decide(self, actor: TeamsActor, action: TeamsAction) -> WorkflowExecution:
        reviewer = self.authorize(actor)
        return self.engine.decide(
            action.run_id, reviewer=reviewer, decision=action.decision,
            comment=action.comment, expected_approval_id=action.approval_id,
        )

    def pending(self, run_id: str) -> ApprovalRequest:
        return self.engine.pending_approval(run_id)
