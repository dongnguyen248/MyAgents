from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, Field

from asf.configuration.platform import ConfigModel

__all__ = [
    "AgentRunRecord",
    "ApprovalRecord",
    "QualityKind",
    "QualityRecord",
]

QualityKind = Literal["TEST", "CI", "REVIEW"]


class AgentRunRecord(ConfigModel):
    """One recorded ``AgentResult``, reduced to the fields metrics aggregate."""

    recorded_at: AwareDatetime
    agent_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    project_id: str | None = None
    task_id: str | None = None
    status: Literal["SUCCESS", "FAILED", "REJECTED", "WAITING", "CANCELLED"]
    duration_seconds: float = Field(ge=0)
    revision_count: int = Field(ge=0)
    attempt: int = Field(ge=1)
    # Platform-accumulated model usage (defaults keep old snapshots
    # restorable).
    run_id: str | None = None
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    model_calls: int = Field(default=0, ge=0)


class ApprovalRecord(ConfigModel):
    """One approval decision attributed to an agent, tagged by decider kind."""

    recorded_at: AwareDatetime
    project_id: str = Field(min_length=1)
    task_id: str | None = None
    agent_id: str = Field(min_length=1)
    decision: Literal["APPROVED", "REJECTED", "REQUEST_CHANGES"]
    reviewer_kind: Literal["HUMAN", "AI"] = "HUMAN"


class QualityRecord(ConfigModel):
    """One pass/fail quality sample (a test run, a CI run, or a code review)."""

    recorded_at: AwareDatetime
    project_id: str | None = None
    task_id: str | None = None
    agent_id: str = Field(min_length=1)
    kind: QualityKind
    passed: bool
