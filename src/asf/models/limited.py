"""A ModelGateway decorator that bounds concurrent model calls.

Parallel run drives are good for throughput and bad for provider
quotas: N runs stepping at once meant N model calls in flight, and
the burst is exactly what trips a provider's rate limiter (HTTP 429
for every run at the same time). Wrapping the routed gateway in this
limiter caps the number of calls executing concurrently across ALL
runs and agents; excess calls wait for a slot. The limiter is
provider-agnostic — it wraps the ModelGateway port, not any adapter.
"""

from __future__ import annotations

import threading

from asf.contracts.models import ModelRequest, ModelResponse
from asf.models.ports import ModelGateway

__all__ = ["ConcurrencyLimitedGateway"]


class ConcurrencyLimitedGateway:
    """Serializes access to an inner gateway through a semaphore."""

    def __init__(self, inner: ModelGateway, *, max_concurrent: int) -> None:
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be at least 1")
        self._inner = inner
        self._max_concurrent = max_concurrent
        self._semaphore = threading.BoundedSemaphore(max_concurrent)

    @property
    def max_concurrent(self) -> int:
        return self._max_concurrent

    def complete(self, request: ModelRequest) -> ModelResponse:
        with self._semaphore:
            return self._inner.complete(request)
