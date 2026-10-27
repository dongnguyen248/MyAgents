from __future__ import annotations

from datetime import datetime
from typing import Any

from asf.contracts.models import PlatformError

__all__ = ["ALLOWED_GATEWAY_ERROR_CODES", "ModelGatewayError"]

ALLOWED_GATEWAY_ERROR_CODES: dict[str, tuple[str, bool]] = {
    "LLM_TIMEOUT": ("LLM", True),
    "LLM_RATE_LIMITED": ("LLM", True),
    "LLM_INVALID_RESPONSE": ("LLM", True),
    "INTEGRATION_UNAVAILABLE": ("INTEGRATION", True),
}


class ModelGatewayError(Exception):
    """Raised when a ModelGateway call fails."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        if code not in ALLOWED_GATEWAY_ERROR_CODES:
            allowed = sorted(ALLOWED_GATEWAY_ERROR_CODES)
            raise ValueError(f"Unknown gateway error code '{code}'. Allowed: {allowed}")
        super().__init__(message)
        self.code = code
        self.message = message
        category, retryable = ALLOWED_GATEWAY_ERROR_CODES[code]
        self.category = category
        self.retryable = retryable
        self.details = dict(details or {})

    def to_platform_error(self, now: datetime) -> dict[str, Any]:
        """Converts this error to a PlatformError contract dictionary."""
        if not isinstance(now, datetime):
            raise TypeError("now must be a datetime instance")
        if now.tzinfo is None or now.tzinfo.utcoffset(now) is None:
            raise ValueError("now must be a timezone-aware datetime")

        err = PlatformError(
            code=self.code,
            message=self.message,
            category=self.category,  # type: ignore[arg-type]
            details=self.details,
            retryable=self.retryable,
            timestamp=now,
        )
        return err.to_contract()
