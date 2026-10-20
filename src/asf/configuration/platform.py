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


class RetryPolicySettings(ConfigModel):
    max_attempts: int = Field(ge=1)
    backoff_seconds: float | None = Field(default=None, ge=0)
    retry_on: list[str] | None = None

    @model_validator(mode="after")
    def validate_retry_on_unique(self) -> RetryPolicySettings:
        if self.retry_on is not None and len(self.retry_on) != len(set(self.retry_on)):
            raise ValueError("retryOn items must be unique")
        return self


class AgentSettings(ConfigModel):
    model_profile: str | None = None
    timeout_seconds: int | None = Field(default=None, ge=1)
    retry_policy: RetryPolicySettings | None = None
    settings: dict[str, Any] = Field(default_factory=dict)


class PlatformConfig(ConfigModel):
    version: Literal[1] = 1
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    paths: PathsConfig = Field(default_factory=PathsConfig)
    models: ModelsConfig = Field(default_factory=ModelsConfig)
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
