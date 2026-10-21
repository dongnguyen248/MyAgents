from __future__ import annotations

from typing import Any, Literal

from pydantic import AwareDatetime, Field, field_validator, model_validator

from asf.configuration.platform import ConfigModel

__all__ = [
    "ApprovalDecision",
    "ApprovalFeedback",
    "ApprovalPolicy",
    "ApprovalRequest",
    "ApprovalSpec",
]


class ApprovalPolicy(ConfigModel):
    min_approvals: int = Field(default=1, ge=1)
    reviewers: list[str] = Field(min_length=1)
    expires_in_seconds: int | None = Field(default=None, ge=1)

    @field_validator("reviewers")
    @classmethod
    def _validate_reviewers(cls, reviewers: list[str]) -> list[str]:
        if not reviewers:
            raise ValueError("Reviewers list must not be empty")
        for r in reviewers:
            if not isinstance(r, str) or not r:
                raise ValueError("Reviewer identifier must be a non-empty string")
        if len(reviewers) != len(set(reviewers)):
            raise ValueError("Reviewers list must contain unique identifiers")
        return reviewers

    @model_validator(mode="after")
    def _validate_policy_invariants(self) -> ApprovalPolicy:
        if self.min_approvals > len(self.reviewers):
            raise ValueError(
                f"min_approvals ({self.min_approvals}) cannot exceed "
                f"number of reviewers ({len(self.reviewers)})"
            )
        return self

    def to_contract(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json")


class ApprovalRequest(ConfigModel):
    id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    artifact_id: str = Field(min_length=1)
    type: str = Field(min_length=1)
    status: Literal[
        "PENDING",
        "APPROVED",
        "REJECTED",
        "CHANGES_REQUESTED",
        "CANCELLED",
        "EXPIRED",
    ]
    requested_by: str = Field(min_length=1)
    requested_at: AwareDatetime
    expires_at: AwareDatetime | None = None
    min_approvals: int = Field(ge=1)
    reviewers: list[str] = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("reviewers")
    @classmethod
    def _validate_reviewers(cls, reviewers: list[str]) -> list[str]:
        if not reviewers:
            raise ValueError("Reviewers list must not be empty")
        for r in reviewers:
            if not isinstance(r, str) or not r:
                raise ValueError("Reviewer identifier must be a non-empty string")
        if len(reviewers) != len(set(reviewers)):
            raise ValueError("Reviewers list must contain unique identifiers")
        return reviewers

    @model_validator(mode="after")
    def _validate_request_invariants(self) -> ApprovalRequest:
        if self.min_approvals > len(self.reviewers):
            raise ValueError(
                f"min_approvals ({self.min_approvals}) cannot exceed "
                f"number of reviewers ({len(self.reviewers)})"
            )
        return self

    def to_contract(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json")


class ApprovalDecision(ConfigModel):
    approval_id: str = Field(min_length=1)
    decision: Literal["APPROVED", "REJECTED", "REQUEST_CHANGES"]
    reviewer: str = Field(min_length=1)
    comment: str = ""
    created_at: AwareDatetime

    def to_contract(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json")


class ApprovalFeedback(ConfigModel):
    approval_id: str = Field(min_length=1)
    reviewer: str = Field(min_length=1)
    decision: Literal["REJECTED", "REQUEST_CHANGES"]
    comment: str = Field(min_length=1)

    def to_contract(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json")


class ApprovalSpec(ConfigModel):
    task_id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    artifact_id: str = Field(min_length=1)
    type: str = Field(min_length=1)
    requested_by: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
