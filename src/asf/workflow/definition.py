from __future__ import annotations

from typing import Any, Self

from pydantic import Field, model_validator
from pydantic_core import InitErrorDetails, ValidationError

from asf.configuration.loader import validation_error_to_config_error
from asf.configuration.platform import ConfigModel, RetryPolicySettings

DEFAULT_MAX_REVISIONS: int = 3
RESERVED_STAGES = frozenset({"NEW", "COMPLETED", "FAILED", "CANCELLED"})

__all__ = [
    "DEFAULT_MAX_REVISIONS",
    "RESERVED_STAGES",
    "WorkflowDefinition",
    "WorkflowStepDef",
    "validation_error_to_config_error",
]


class WorkflowStepDef(ConfigModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    type: str = Field(min_length=1)
    stage: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    requires_approval: bool
    agent_type: str | None = None
    action: str | None = None
    timeout: int | None = Field(default=None, ge=1)
    retry_policy: RetryPolicySettings | None = None
    configuration: dict[str, Any] = Field(default_factory=dict)
    consumes: list[str] = Field(default_factory=list)
    produces: list[str] = Field(default_factory=list)
    max_revisions: int | None = Field(default=None, ge=0)

    @model_validator(mode="before")
    @classmethod
    def _default_max_revisions(cls, data: Any) -> Any:
        if isinstance(data, dict):
            req = data.get("requires_approval")
            if req is None:
                req = data.get("requiresApproval", False)
            max_rev = data.get("max_revisions")
            if max_rev is None and "maxRevisions" in data:
                max_rev = data.get("maxRevisions")
            if req and max_rev is None:
                copied = dict(data)
                copied["max_revisions"] = DEFAULT_MAX_REVISIONS
                return copied
        return data

    @model_validator(mode="after")
    def _validate_step(self) -> Self:
        errs: list[InitErrorDetails] = []

        if self.agent_type is None and self.action is None:
            errs.append(
                {
                    "type": "value_error",
                    "loc": ("agentType",),
                    "input": None,
                    "ctx": {
                        "error": ValueError(
                            "Step must specify at least one of agentType or action"
                        )
                    },
                }
            )

        if len(self.consumes) != len(set(self.consumes)):
            errs.append(
                {
                    "type": "value_error",
                    "loc": ("consumes",),
                    "input": self.consumes,
                    "ctx": {"error": ValueError("Items in consumes must be unique")},
                }
            )
        for item in self.consumes:
            if not item:
                errs.append(
                    {
                        "type": "value_error",
                        "loc": ("consumes",),
                        "input": self.consumes,
                        "ctx": {
                            "error": ValueError(
                                "Items in consumes must be non-empty strings"
                            )
                        },
                    }
                )

        if len(self.produces) != len(set(self.produces)):
            errs.append(
                {
                    "type": "value_error",
                    "loc": ("produces",),
                    "input": self.produces,
                    "ctx": {"error": ValueError("Items in produces must be unique")},
                }
            )
        for item in self.produces:
            if not item:
                errs.append(
                    {
                        "type": "value_error",
                        "loc": ("produces",),
                        "input": self.produces,
                        "ctx": {
                            "error": ValueError(
                                "Items in produces must be non-empty strings"
                            )
                        },
                    }
                )

        if not self.requires_approval and self.max_revisions is not None:
            errs.append(
                {
                    "type": "value_error",
                    "loc": ("max_revisions",),
                    "input": self.max_revisions,
                    "ctx": {
                        "error": ValueError(
                            "maxRevisions can only be specified when requiresApproval is true"
                        )
                    },
                }
            )

        if errs:
            raise ValidationError.from_exception_data("WorkflowStepDef", errs)
        return self

    def generated_stages(self) -> list[str]:
        if self.requires_approval:
            return [
                f"{self.stage}_DRAFT",
                f"{self.stage}_REVIEW",
                f"{self.stage}_REJECTED",
                f"{self.stage}_APPROVED",
                f"{self.stage}_ESCALATED",
            ]
        return [self.stage]

    def to_contract(self) -> dict[str, Any]:
        res: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "stage": self.stage,
            "requiresApproval": self.requires_approval,
        }
        if self.agent_type is not None:
            res["agentType"] = self.agent_type
        if self.action is not None:
            res["action"] = self.action
        if self.timeout is not None:
            res["timeout"] = self.timeout
        if self.retry_policy is not None:
            res["retryPolicy"] = self.retry_policy.model_dump(
                by_alias=True, mode="json", exclude_none=True
            )
        if self.configuration:
            res["configuration"] = self.configuration
        else:
            res["configuration"] = {}
        if self.consumes:
            res["consumes"] = list(self.consumes)
        if self.produces:
            res["produces"] = list(self.produces)
        if self.requires_approval:
            res["maxRevisions"] = self.max_revisions
        return res


class WorkflowDefinition(ConfigModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    steps: list[WorkflowStepDef] = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_workflow_definition(self) -> Self:
        errs: list[InitErrorDetails] = []

        # 1. Step IDs unique
        seen_ids: set[str] = set()
        for idx, step in enumerate(self.steps):
            if step.id in seen_ids:
                errs.append(
                    {
                        "type": "value_error",
                        "loc": ("steps", idx, "id"),
                        "input": step.id,
                        "ctx": {"error": ValueError(f"Duplicate step id '{step.id}'")},
                    }
                )
            seen_ids.add(step.id)

        # 2. GENERATED stage names across all steps are unique and not reserved
        seen_stages: dict[str, int] = {}
        for idx, step in enumerate(self.steps):
            gen_stages = step.generated_stages()
            for stage_name in gen_stages:
                if stage_name in RESERVED_STAGES or step.stage in RESERVED_STAGES:
                    msg = (
                        f"Step stage '{step.stage}' conflicts with "
                        f"reserved stage name '{stage_name}'"
                    )
                    errs.append(
                        {
                            "type": "value_error",
                            "loc": ("steps", idx, "stage"),
                            "input": step.stage,
                            "ctx": {"error": ValueError(msg)},
                        }
                    )
                if stage_name in seen_stages:
                    first_idx = seen_stages[stage_name]
                    msg = (
                        f"Generated stage '{stage_name}' duplicates or collides "
                        f"with stage generated by step index {first_idx}"
                    )
                    errs.append(
                        {
                            "type": "value_error",
                            "loc": ("steps", idx, "stage"),
                            "input": step.stage,
                            "ctx": {"error": ValueError(msg)},
                        }
                    )
                else:
                    seen_stages[stage_name] = idx

        # 3. Every consumed artifact type is produced by an EARLIER step
        produced_so_far: set[str] = set()
        for idx, step in enumerate(self.steps):
            for art in step.consumes:
                if art not in produced_so_far:
                    msg = f"Consumed artifact '{art}' is not produced by an earlier step"
                    errs.append(
                        {
                            "type": "value_error",
                            "loc": ("steps", idx, "consumes"),
                            "input": step.consumes,
                            "ctx": {"error": ValueError(msg)},
                        }
                    )
            produced_so_far.update(step.produces)

        if errs:
            raise ValidationError.from_exception_data(
                "WorkflowDefinition",
                errs,
            )
        return self

    def to_contract(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "steps": [s.to_contract() for s in self.steps],
            "metadata": dict(self.metadata),
        }
