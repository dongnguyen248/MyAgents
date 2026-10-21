from __future__ import annotations

from enum import StrEnum


class Trigger(StrEnum):
    START = "START"
    COMPLETE = "COMPLETE"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REQUEST_CHANGES = "REQUEST_CHANGES"
    ADVANCE = "ADVANCE"
    REVISE = "REVISE"
    RESUME = "RESUME"
    FAIL = "FAIL"
    CANCEL = "CANCEL"


class StageKind(StrEnum):
    INITIAL = "INITIAL"
    DRAFT = "DRAFT"
    REVIEW = "REVIEW"
    REJECTED = "REJECTED"
    APPROVED = "APPROVED"
    ESCALATED = "ESCALATED"
    STEP = "STEP"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
