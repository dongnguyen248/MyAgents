"""Per-run model budget: the orchestrator's cost ceiling.

A run whose recorded usage (the platform-accumulated
``RunMetrics`` of its step results) exceeds any configured
dimension is failed with ``RUN_BUDGET_EXCEEDED`` BEFORE the next
dispatch — the model is never called again for that run. ``None``
dimensions are unlimited. The check is the orchestrator's, not an
agent's: budgets are a platform policy over the whole run,
including repair calls and fix-loop cycles.
"""

from __future__ import annotations

from pydantic import Field

from asf.configuration.platform import ConfigModel
from asf.orchestrator.execution import WorkflowExecution

__all__ = ["RunBudget", "budget_exceeded_message"]


class RunBudget(ConfigModel):
    max_prompt_tokens: int | None = Field(default=None, ge=1)
    max_completion_tokens: int | None = Field(default=None, ge=1)
    max_model_calls: int | None = Field(default=None, ge=1)


def budget_exceeded_message(
    run: WorkflowExecution, budget: RunBudget,
) -> str | None:
    """Why this run is over budget, or None when it is within it."""
    prompt = sum(result.metrics.prompt_tokens for result in run.results)
    completion = sum(
        result.metrics.completion_tokens for result in run.results
    )
    calls = sum(result.metrics.model_calls for result in run.results)
    checks = (
        ("prompt tokens", prompt, budget.max_prompt_tokens),
        ("completion tokens", completion, budget.max_completion_tokens),
        ("model calls", calls, budget.max_model_calls),
    )
    for label, used, limit in checks:
        if limit is not None and used > limit:
            return (
                f"Run budget exceeded: {label} used {used},"
                f" limit is {limit}. The run was stopped before"
                " dispatching another step; raise the budget in the"
                " platform configuration to let runs spend more."
            )
    return None
