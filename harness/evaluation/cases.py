"""Benchmark case definitions for offline agent evaluation."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["BenchmarkCase", "load_cases"]


class BenchmarkCase(BaseModel):
    """One deterministic benchmark: a requirement and what the chain must produce."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    requirement: str = Field(min_length=1)
    expected_artifacts: list[str] = Field(default_factory=list)
    max_revisions: int = Field(default=0, ge=0)
    must_complete: bool = True


def load_cases(directory: Path | str) -> list[BenchmarkCase]:
    """Load every ``*.json`` benchmark case in *directory*, sorted by file name."""
    root = Path(directory)
    cases: list[BenchmarkCase] = []
    for path in sorted(root.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        cases.append(BenchmarkCase.model_validate(data))
    return cases
