from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from asf.configuration.secrets import SecretRef


class ConfigModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        alias_generator=to_camel,
        populate_by_name=True,
    )


class PathsConfig(ConfigModel):
    artifacts_dir: str = "artifacts"


class ModelProfile(ConfigModel):
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    endpoint: str | None = None
    credentials: SecretRef | None = None
    timeout_seconds: float = Field(default=60.0, gt=0)
    parameters: dict[str, Any] = Field(default_factory=dict)


class ModelsConfig(ConfigModel):
    default: str | None = None
    profiles: dict[str, ModelProfile] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_default_profile(self) -> ModelsConfig:
        if self.default is not None and self.default not in self.profiles:
            raise ValueError(
                f"Default model profile '{self.default}' does not exist in models.profiles"
            )
        return self


class ServiceConfig(ConfigModel):
    provider: str = Field(min_length=1)
    endpoint: str | None = None
    credentials: SecretRef | None = None
    settings: dict[str, Any] = Field(default_factory=dict)


class NotificationChannel(ConfigModel):
    name: str = Field(min_length=1)
    type: str = Field(min_length=1)
    endpoint: str | None = None
    credentials: SecretRef | None = None
    settings: dict[str, Any] = Field(default_factory=dict)


# Agent/infrastructure codes a retry policy may name, on top of the
# gateway codes (imported lazily in the validator: asf.models.errors
# depends on the contracts package, which depends back on this
# module's package — a module-level import would close a cycle).
# Anything outside the combined set is a typo that would silently
# disable retries (the example config once shipped TIMEOUT /
# RATE_LIMITED, which match nothing).
_AGENT_RETRY_ON_CODES: frozenset[str] = frozenset({
    "AGENT_EXECUTION_FAILED",
    "WORKFLOW_STEP_TIMEOUT",
    "COMMAND_TIMEOUT",
    "SANDBOX_ERROR",
    "REPOSITORY_ERROR",
    "GIT_OPERATION_FAILED",
    "CI_UNAVAILABLE",
    # Hosting actions report these while CI / a merge is in flight;
    # the shipped development workflow retries on exactly them.
    "PIPELINE_RUNNING",
    "MERGE_PENDING",
})


class RetryPolicySettings(ConfigModel):
    max_attempts: int = Field(ge=1)
    backoff_seconds: float | None = Field(default=None, ge=0)
    retry_on: list[str] | None = None

    @model_validator(mode="after")
    def validate_retry_on_unique(self) -> RetryPolicySettings:
        if self.retry_on is not None and len(self.retry_on) != len(set(self.retry_on)):
            raise ValueError("retryOn items must be unique")
        return self

    @model_validator(mode="after")
    def validate_retry_on_codes(self) -> RetryPolicySettings:
        if self.retry_on:
            from asf.models.errors import ALLOWED_GATEWAY_ERROR_CODES

            valid = frozenset(ALLOWED_GATEWAY_ERROR_CODES) | _AGENT_RETRY_ON_CODES
            unknown = [code for code in self.retry_on if code not in valid]
            if unknown:
                raise ValueError(
                    f"Unknown retryOn code(s): {', '.join(unknown)}. "
                    f"Valid codes: {', '.join(sorted(valid))}"
                )
        return self


class AgentSettings(ConfigModel):
    model_profile: str | None = None
    timeout_seconds: int | None = Field(default=None, ge=1)
    retry_policy: RetryPolicySettings | None = None
    settings: dict[str, Any] = Field(default_factory=dict)


class ExecutionConfig(ConfigModel):
    """Bounds on how much work the platform runs at the same time."""

    max_concurrent_runs: int = Field(default=2, ge=1)
    max_concurrent_model_calls: int = Field(default=2, ge=1)


class RunBudgetSettings(ConfigModel):
    """Per-run model spending ceiling (None dimension = unlimited).

    Enforced by the orchestrator before every dispatch: a run over
    budget fails with RUN_BUDGET_EXCEEDED and the model is not
    called again for it.
    """

    max_prompt_tokens: int | None = Field(default=None, ge=1)
    max_completion_tokens: int | None = Field(default=None, ge=1)
    max_model_calls: int | None = Field(default=None, ge=1)


class PlatformConfig(ConfigModel):
    version: Literal[1] = 1
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    paths: PathsConfig = Field(default_factory=PathsConfig)
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    budget: RunBudgetSettings = Field(default_factory=RunBudgetSettings)
    source_control: ServiceConfig | None = None
    ci: ServiceConfig | None = None
    notifications: list[NotificationChannel] = Field(default_factory=list)
    agents: dict[str, AgentSettings] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_platform_integrity(self) -> PlatformConfig:
        # Check notification names unique
        names = [n.name for n in self.notifications]
        if len(names) != len(set(names)):
            raise ValueError("Notification channel names must be unique")

        # Check agents reference valid model profiles
        for agent_name, agent_cfg in self.agents.items():
            if (
                agent_cfg.model_profile is not None
                and agent_cfg.model_profile not in self.models.profiles
            ):
                msg = (
                    f"Agent '{agent_name}' references unknown "
                    f"modelProfile '{agent_cfg.model_profile}'"
                )
                raise ValueError(msg)
        return self
