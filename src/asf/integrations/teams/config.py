from __future__ import annotations

import re
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from asf.approval.models import validate_reviewer_identifier
from asf.configuration.platform import ConfigModel, NotificationChannel
from asf.configuration.secrets import SecretRef


class TeamsConfig(ConfigModel):
    """Power Automate destination and callback trust; no registered bot required."""

    tenant_id: UUID
    team_id: UUID
    channel_id: str = Field(min_length=1, max_length=512)
    workflow_host: str = Field(min_length=1, max_length=253)
    credentials: SecretRef
    callback_secret: SecretRef
    reviewers: dict[UUID, str] = Field(min_length=1)
    timeout_seconds: float = Field(default=30, gt=0, le=120)

    @field_validator("channel_id")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if value != value.strip() or not value:
            raise ValueError("Teams identifiers must be nonblank without surrounding whitespace")
        return value

    @field_validator("workflow_host")
    @classmethod
    def hostname(cls, value: str) -> str:
        if (
            re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", value) is None
            or "." not in value or ".." in value or value.endswith(".local")
            or not value.rsplit(".", 1)[-1].isalpha()
        ):
            raise ValueError("workflowHost must be the exact lowercase trigger hostname")
        return value

    @model_validator(mode="after")
    def distinct_reviewers(self) -> TeamsConfig:
        for reviewer in self.reviewers.values():
            validate_reviewer_identifier(reviewer)
        if len(set(self.reviewers.values())) != len(self.reviewers):
            raise ValueError("Each Teams identity must map to a distinct reviewer")
        return self

    @classmethod
    def from_channel(cls, channel: NotificationChannel) -> TeamsConfig:
        if channel.type != "teams-workflow" or channel.credentials is None:
            raise ValueError("Teams requires a teams-workflow channel and environment credentials")
        if channel.endpoint is not None:
            raise ValueError("Store the full workflow URL in an environment reference")
        return cls.model_validate({**channel.settings, "credentials": channel.credentials})

    def resolve_workflow_url(self) -> str:
        value = self.credentials.resolve()
        try:
            url = urlsplit(value)
            valid = (
                url.scheme == "https" and url.hostname == self.workflow_host
                and url.port in (None, 443) and url.username is None and url.password is None
                and not url.fragment and url.path.startswith("/") and url.path != "/"
                and not any(char.isspace() or ord(char) < 32 for char in value)
                and "\\" not in value
            )
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("Workflow URL must use HTTPS/443 on the configured trigger host") \
                from None
        return value
