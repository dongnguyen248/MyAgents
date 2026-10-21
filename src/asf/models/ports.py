from __future__ import annotations

from typing import Protocol

from asf.contracts.models import ModelRequest, ModelResponse

__all__ = ["ModelGateway"]


class ModelGateway(Protocol):
    """Port for language model completion."""

    def complete(self, request: ModelRequest) -> ModelResponse:
        """Invokes a language model and returns its response."""
        ...
