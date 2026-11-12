"""The "Now" enrichment of one run's currentActivity.

The workflow view's ``currentActivity`` says a step is running
since some moment; the run page's "Now" card needs more: WHO is
acting, with which model, in which phase, on which attempt, and
what the run did last. Everything here derives from state the
engine already persists (waiting derivation, step definitions,
revision/attempt counters, the observation trail) — nothing is
recorded for this feature, and it is computed only for the
single-run workflow view, never for list endpoints.

Phase derivation (from the waiting kind, then the active step):

- ``AI_REVIEWING`` — waiting kind AI_REVIEW; the actor is the
  artifact-review agent and the attempt is the review round.
- ``WAITING_FOR_APPROVAL`` — waiting kind APPROVAL; a human gate,
  so no agent and no model.
- ``RETRYING`` — waiting kind RETRY_WAIT; the attempt is the
  pending execution under the failed step's retry policy.
- ``ESCALATED`` / ``STALLED`` / ``PAUSED`` — the waiting kinds of
  the same names; the attempt mirrors the fix budget when the
  escalation carries one.
- ``FIXING`` — a code-loop stage (CODE_FIX / CODE_REWORK); the
  actor is the Fix agent and the attempt is the fix budget.
- ``WAITING_ON_CI`` / ``WAITING_FOR_MERGE`` — the active step's
  action is ``run-pipeline`` / ``await-merge``; no agent, no model.
- ``RUNNING_TESTS`` — the active step's agent is the Test agent;
  it never calls a model, so the model stays null.
- ``PRODUCING`` — any other identifiable agent step in flight.
- ``None`` — the active step cannot be identified from persisted
  state; the UI falls back to its generic line.

The model is the settings-effective model at view time
(``ModelSettings.effective_model``): the settings are read per
call and there is no per-run snapshot, so a mid-run settings
change makes this the model the NEXT call will use. It is a model
NAME only — never a key or a credential.
"""

from __future__ import annotations

from typing import Any

from asf.agents._shared.security import redact_text
from asf.api.service import _iso
from asf.orchestrator.code_loop import FIX_STAGE, REWORK_STAGE
from asf.orchestrator.execution import WorkflowExecution

__all__ = ["enrich_activity"]

_ARTIFACT_REVIEW_AGENT = "agent-artifact-review"
_TEST_AGENT = "agent-test"
_FIX_AGENT = "agent-fix"
_MAX_EVENTS = 10
_MAX_EVENT_CHARS = 240


def enrich_activity(
    service: Any,
    run: WorkflowExecution,
    activity: dict[str, Any],
) -> dict[str, Any]:
    """Add the Now fields to a non-terminal run's currentActivity."""
    waiting = service._waiting(run, service._workflow_status(run))
    enriched = dict(activity)
    enriched.update(
        {
            "agentId": None,
            "agentName": None,
            "model": None,
            "phase": None,
            "attempt": None,
            "attemptMax": None,
        }
    )
    _apply_phase(service, run, waiting, enriched)
    agent_id = enriched["agentId"]
    if isinstance(agent_id, str):
        metadata = service._metadata(agent_id)
        enriched["agentName"] = metadata.name if metadata is not None else None
        enriched["model"] = _model_for(service, run, agent_id)
    last_at, events = _recent_events(run)
    enriched["lastEventAt"] = last_at
    enriched["recentEvents"] = events
    return enriched


def _apply_phase(
    service: Any,
    run: WorkflowExecution,
    waiting: dict[str, Any],
    enriched: dict[str, Any],
) -> None:
    kind = enriched["kind"]
    if kind == "AI_REVIEW":
        enriched["phase"] = "AI_REVIEWING"
        enriched["agentId"] = _ARTIFACT_REVIEW_AGENT
        enriched["attempt"] = waiting.get("round")
        enriched["attemptMax"] = waiting.get("maxRounds")
        return
    if kind == "APPROVAL":
        enriched["phase"] = "WAITING_FOR_APPROVAL"
        return
    if kind == "RETRY_WAIT":
        enriched["phase"] = "RETRYING"
        _apply_retry_attempt(service, run, enriched)
        return
    if kind in ("ESCALATED", "STALLED", "PAUSED"):
        enriched["phase"] = kind
        budget = waiting.get("budget")
        if kind == "ESCALATED" and isinstance(budget, dict):
            enriched["attempt"] = budget["used"]
            enriched["attemptMax"] = budget["max"]
        return
    if kind == "STEP_RUNNING":
        _apply_running(service, run, enriched)


def _apply_retry_attempt(
    service: Any,
    run: WorkflowExecution,
    enriched: dict[str, Any],
) -> None:
    step = service._step_for_stage(run, run.state.stage)
    _policy_attempt(step.retry_policy if step is not None else None, run, enriched)


def _policy_attempt(
    policy: Any,
    run: WorkflowExecution,
    enriched: dict[str, Any],
) -> None:
    if policy is not None:
        enriched["attempt"] = min(run.retry_attempts + 1, policy.max_attempts)
        enriched["attemptMax"] = policy.max_attempts


def _apply_running(
    service: Any,
    run: WorkflowExecution,
    enriched: dict[str, Any],
) -> None:
    stage = run.state.stage
    if stage in (FIX_STAGE, REWORK_STAGE):
        budget = service._fix_budget(run)
        enriched["phase"] = "FIXING"
        enriched["agentId"] = _FIX_AGENT
        enriched["attempt"] = min(budget["used"] + 1, budget["max"])
        enriched["attemptMax"] = budget["max"]
        return
    step = service._step_for_stage(run, stage)
    if step is None:
        return
    if step.action == "run-pipeline":
        enriched["phase"] = "WAITING_ON_CI"
        return
    if step.action == "await-merge":
        enriched["phase"] = "WAITING_FOR_MERGE"
        return
    _apply_agent_step(service, step, run, enriched)


def _apply_agent_step(
    service: Any,
    step: Any,
    run: WorkflowExecution,
    enriched: dict[str, Any],
) -> None:
    agent_id = service._agent_id_for_type(step.agent_type)
    if agent_id is None:
        return
    enriched["agentId"] = agent_id
    if agent_id == _TEST_AGENT:
        enriched["phase"] = "RUNNING_TESTS"
        return
    enriched["phase"] = "PRODUCING"
    if run.retry_attempts > 0:
        _policy_attempt(step.retry_policy, run, enriched)


def _model_for(service: Any, run: WorkflowExecution, agent_id: str) -> str | None:
    if agent_id == _TEST_AGENT:
        return None
    settings = getattr(service, "_model_settings", None)
    if settings is None:
        return None
    tier = run.context.get("modelTier") if isinstance(run.context, dict) else None
    model = settings.effective_model(agent_id, tier if isinstance(tier, str) else None)
    return model or None


def _recent_events(
    run: WorkflowExecution,
) -> tuple[str | None, list[dict[str, Any]]]:
    """The run's last sign of life + its current stage's last events.

    Messages are operator-visible text: redacted first, then capped
    — a secret cut by the cap must not survive (same order as the
    reviewer-failure path). Prompts and raw model output are never
    written to the event trail, so they cannot appear here.
    """
    events = [obs.event for obs in run.observations if obs.event is not None]
    if not events:
        return None, []
    stage_events = [event for event in events if event.metadata.get("stage") == run.state.stage][
        -_MAX_EVENTS:
    ]
    shaped = [
        {
            "type": event.event_type,
            "message": redact_text(event.message)[:_MAX_EVENT_CHARS],
            "at": _iso(event.timestamp),
        }
        for event in stage_events
    ]
    return _iso(events[-1].timestamp), shaped
