from __future__ import annotations

from typing import Any, Literal

from pydantic import AwareDatetime, Field, model_validator

from asf.approval.models import ApprovalFeedback
from asf.configuration.platform import ConfigModel

__all__ = [
    "ActivityEvent",
    "AgentMetadata",
    "AgentRequest",
    "AgentResult",
    "ApprovalFeedback",
    "Artifact",
    "ContractModel",
    "ModelMessage",
    "ModelRequest",
    "ModelResponse",
    "ModelUsage",
    "PlatformError",
    "RunMetrics",
    "ValidationResult",
]


class ContractModel(ConfigModel):
    """Base class for all data contract bindings."""

    def to_contract(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json")


class PlatformError(ContractModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    category: Literal[
        "VALIDATION",
        "AGENT",
        "WORKFLOW",
        "APPROVAL",
        "INTEGRATION",
        "LLM",
        "GIT",
        "CI",
        "SYSTEM",
    ]
    details: dict[str, Any] = Field(default_factory=dict)
    retryable: bool
    timestamp: AwareDatetime


class RunMetrics(ContractModel):
    duration_seconds: float = Field(ge=0)
    revision_count: int = Field(ge=0)
    attempt: int = Field(ge=1)


class Artifact(ContractModel):
    id: str = Field(min_length=1)
    type: str = Field(min_length=1)
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    content: Any | None = None
    reference: str | None = Field(default=None, min_length=1)
    created_by: str = Field(min_length=1)
    created_at: AwareDatetime
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_content_or_reference(self) -> Artifact:
        if self.content is None and self.reference is None:
            raise ValueError("Artifact must have either 'content' or 'reference' (or both)")
        return self

    def to_contract(self) -> dict[str, Any]:
        d = super().to_contract()
        if self.content is None and "content" in d:
            del d["content"]
        if self.reference is None and "reference" in d:
            del d["reference"]
        return d


class ActivityEvent(ContractModel):
    id: str = Field(min_length=1)
    timestamp: AwareDatetime
    project_id: str = Field(min_length=1)
    task_id: str | None = None
    workflow_id: str | None = None
    agent_id: str | None = None
    event_type: str = Field(min_length=1)
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentMetadata(ContractModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    type: str = Field(min_length=1)
    version: str = Field(min_length=1)
    status: Literal["IDLE", "RUNNING", "WAITING", "ERROR", "DISABLED", "OFFLINE"]
    capabilities: list[str] = Field(default_factory=list)
    configuration: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_capabilities(self) -> AgentMetadata:
        for cap in self.capabilities:
            if not isinstance(cap, str) or len(cap) < 1:
                raise ValueError("Capability must be a non-empty string")
        if len(self.capabilities) != len(set(self.capabilities)):
            raise ValueError("capabilities items must be unique")
        return self


class ValidationResult(ContractModel):
    valid: bool
    errors: list[PlatformError] = Field(default_factory=list)


class ModelMessage(ContractModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ModelUsage(ContractModel):
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)


class ModelRequest(ContractModel):
    messages: list[ModelMessage] = Field(min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)
    model: str | None = Field(default=None, min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_contract(self) -> dict[str, Any]:
        d = super().to_contract()
        if self.model is None and "model" in d:
            del d["model"]
        return d


class ModelResponse(ContractModel):
    content: str
    model: str = Field(min_length=1)
    usage: ModelUsage
    finish_reason: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentRequest(ContractModel):
    request_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    input: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[Artifact] = Field(default_factory=list)
    feedback: list[ApprovalFeedback] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_contract(self) -> dict[str, Any]:
        d = super().to_contract()
        d["artifacts"] = [a.to_contract() for a in self.artifacts]
        return d


class AgentResult(ContractModel):
    request_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    status: Literal["SUCCESS", "FAILED", "REJECTED", "WAITING", "CANCELLED"]
    output: Any | None = None
    artifacts: list[Artifact] = Field(default_factory=list)
    events: list[ActivityEvent] = Field(default_factory=list)
    metrics: RunMetrics
    errors: list[PlatformError] = Field(default_factory=list)

    def to_contract(self) -> dict[str, Any]:
        d = super().to_contract()
        d["artifacts"] = [a.to_contract() for a in self.artifacts]
        return d
