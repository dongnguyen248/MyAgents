"""Harness² adapter seam: protocol, local rules adapter, null (default) adapter."""

from harness.harness2.adapter import (
    Harness2Adapter,
    LocalHarness2Adapter,
    NullHarness2Adapter,
    Suggestion,
    default_adapter,
)

__all__ = [
    "Harness2Adapter",
    "LocalHarness2Adapter",
    "NullHarness2Adapter",
    "Suggestion",
    "default_adapter",
]
