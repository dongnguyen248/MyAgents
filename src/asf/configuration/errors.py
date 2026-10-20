from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class ConfigIssue:
    path: str
    message: str


class ConfigError(Exception):
    def __init__(
        self,
        message: str | None = None,
        *,
        issues: tuple[ConfigIssue, ...] | list[ConfigIssue] = (),
        source: str | None = None,
    ) -> None:
        if isinstance(issues, list):
            issues = tuple(issues)
        self.issues: tuple[ConfigIssue, ...] = issues
        self.source: str | None = source

        if not message:
            if issues:
                joined = "; ".join(f"{iss.path}: {iss.message}" for iss in issues)
                src_part = f" in '{source}'" if source else ""
                message = f"Configuration error{src_part}: {joined}"
            elif source:
                message = f"Configuration error in '{source}'"
            else:
                message = "Configuration error"
        super().__init__(message)

    def to_platform_errors(self, now: datetime | None = None) -> list[dict[str, Any]]:
        ts = (now or datetime.now(timezone.utc)).isoformat()
        errors: list[dict[str, Any]] = []

        if self.issues:
            for issue in self.issues:
                details: dict[str, Any] = {"path": issue.path}
                if self.source is not None:
                    details["source"] = self.source
                errors.append({
                    "code": "VALIDATION_FAILED",
                    "message": f"{issue.path}: {issue.message}",
                    "category": "VALIDATION",
                    "details": details,
                    "retryable": False,
                    "timestamp": ts,
                })
        else:
            details = {}
            if self.source is not None:
                details["source"] = self.source
            errors.append({
                "code": "VALIDATION_FAILED",
                "message": str(self),
                "category": "VALIDATION",
                "details": details,
                "retryable": False,
                "timestamp": ts,
            })
        return errors
