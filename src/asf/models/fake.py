from __future__ import annotations

import copy
from collections.abc import Sequence

from asf.contracts.models import (
    ModelRequest,
    ModelResponse,
    ModelUsage,
)
from asf.models.errors import ModelGatewayError

__all__ = ["ScriptedModelGateway"]


class ScriptedModelGateway:
    """Fake model gateway that plays back a sequence of scripted items."""

    def __init__(
        self,
        script: Sequence[str | ModelResponse | ModelGatewayError | Exception],
    ) -> None:
        self._script: list[str | ModelResponse | ModelGatewayError | Exception] = list(script)
        self._index: int = 0
        self.requests: list[ModelRequest] = []

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(copy.deepcopy(request))

        if self._index >= len(self._script):
            raise RuntimeError("script exhausted")

        item = self._script[self._index]
        self._index += 1

        if isinstance(item, Exception):
            raise item

        if isinstance(item, ModelResponse):
            return item

        if isinstance(item, str):
            model_name = request.model or "scripted-model"
            prompt_words = sum(len(m.content.split()) for m in request.messages)
            completion_words = len(item.split())
            usage = ModelUsage(
                prompt_tokens=prompt_words,
                completion_tokens=completion_words,
            )
            return ModelResponse(
                content=item,
                model=model_name,
                usage=usage,
                finish_reason="stop",
                metadata={},
            )

        raise TypeError(f"Unsupported script item type: {type(item)}")
