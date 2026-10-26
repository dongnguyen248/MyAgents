from __future__ import annotations

import os
import re
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator

from asf.configuration.errors import ConfigError, ConfigIssue

ENV_VAR_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class SecretRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    env: str = Field(min_length=1)

    @field_validator("env")
    @classmethod
    def validate_env_var_name(cls, v: str) -> str:
        if not ENV_VAR_PATTERN.match(v):
            raise ValueError(f"Invalid environment variable name '{v}' in secret reference")
        return v

    def resolve(self, environ: Mapping[str, str] | None = None) -> str:
        env_map = os.environ if environ is None else environ
        if self.env not in env_map:
            raise ConfigError(
                f"Secret environment variable '{self.env}' is not set",
                issues=[
                    ConfigIssue(
                        path="credentials.env",
                        message=f"Environment variable '{self.env}' is not set",
                    )
                ],
            )
        val = env_map[self.env]
        if not val:
            raise ConfigError(
                f"Secret environment variable '{self.env}' is empty",
                issues=[
                    ConfigIssue(
                        path="credentials.env",
                        message=f"Environment variable '{self.env}' is empty",
                    )
                ],
            )
        return val

    def __repr__(self) -> str:
        return f"SecretRef(env='{self.env}')"

    def __str__(self) -> str:
        return f"${{{self.env}}}"
