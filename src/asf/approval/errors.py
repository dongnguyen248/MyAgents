from __future__ import annotations

from datetime import datetime
from typing import Any

__all__ = ["ApprovalError", "ERROR_CATEGORIES"]

ERROR_CATEGORIES: dict[str, str] = {
    "NOT_FOUND": "SYSTEM",
    "VALIDATION_FAILED": "VALIDATION",
    "APPROVAL_EXPIRED": "APPROVAL",
    "APPROVAL_ALREADY_DECIDED": "APPROVAL",
    "APPROVAL_NOT_AUTHORIZED": "APPROVAL",
}


class ApprovalError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        if code not in ERROR_CATEGORIES:
            raise ValueError(f"Unknown approval error code: {code}")
        self.code = code
        self.message = message
        self.details = details if details is not None else {}
        super().__init__(message)

    def to_platform_error(self, now: datetime) -> dict[str, Any]:
        if not isinstance(now, datetime):
            raise TypeError("now must be an instance of datetime")
        if now.tzinfo is None or now.tzinfo.utcoffset(now) is None:
            raise ValueError("Timestamp must be timezone-aware (tzinfo must not be None)")

        return {
            "code": self.code,
            "message": self.message,
            "category": ERROR_CATEGORIES[self.code],
            "retryable": False,
            "details": dict(self.details),
            "timestamp": now.isoformat(),
        }
