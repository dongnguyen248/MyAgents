from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import datetime
from threading import RLock
from typing import Any

from asf.contracts.models import ActivityEvent, AgentResult, Artifact
from asf.evaluation.aggregates import (
    agent_metrics_view,
    ai_decision_record,
    ai_review_metrics,
    human_section,
)
from asf.evaluation.aggregates import (
    mean as _mean,
)
from asf.evaluation.aggregates import (
    rate as _rate,
)
from asf.evaluation.models import AgentRunRecord, ApprovalRecord, QualityRecord

__all__ = ["MetricsService"]

_SNAPSHOT_VERSION = 1
_DECISIONS = ("APPROVED", "REJECTED", "REQUEST_CHANGES")
_QUALITY_KINDS = ("TEST", "CI", "REVIEW")
_TEST_VERDICTS = {"PASS": True, "FAIL": False}  # nosec B105
_REVIEW_VERDICTS = {
    "APPROVE": True,
    "APPROVED": True,
    "CHANGES_REQUESTED": False,
    "REJECTED": False,
}
_FAILED_STATUSES = ("FAILED", "REJECTED")


def _find_verdict(value: Any, allowed: Mapping[str, bool], depth: int = 0) -> bool | None:
    """Best-effort search for a ``verdict`` in an artifact content payload.

    Handles the shapes agents actually emit (``{"report": {"verdict": ...}}``
    for TEST_REPORT, ``{"review": {"verdict": ...}}`` for CODE_REVIEW) as well
    as a top-level verdict or a JSON-encoded string. Anything unrecognised
    returns ``None`` so the sample is ignored.
    """
    if depth > 6:
        return None
    if isinstance(value, dict):
        verdict = value.get("verdict")
        if isinstance(verdict, str) and verdict.upper() in allowed:
            return allowed[verdict.upper()]
        for key in ("report", "review", "result", "data", "content"):
            if key in value:
                found = _find_verdict(value[key], allowed, depth + 1)
                if found is not None:
                    return found
        for item in value.values():
            found = _find_verdict(item, allowed, depth + 1)
            if found is not None:
                return found
    elif isinstance(value, (list, tuple)):
        for item in value:
            found = _find_verdict(item, allowed, depth + 1)
            if found is not None:
                return found
    elif isinstance(value, str) and value.strip()[:1] in ("{", "["):
        try:
            parsed = json.loads(value)
        except ValueError:
            return None
        return _find_verdict(parsed, allowed, depth + 1)
    return None


def _artifact_sample(
    artifact: Artifact,
    *,
    agent_id: str,
    project_id: str | None,
    task_id: str | None,
    recorded_at: datetime,
) -> QualityRecord | None:
    """Derive at most one quality sample from an artifact; never raises."""
    try:
        if artifact.type == "TEST_REPORT":
            passed = _find_verdict(artifact.content, _TEST_VERDICTS)
            if passed is None:
                return None
            return QualityRecord(
                recorded_at=recorded_at,
                project_id=project_id,
                task_id=task_id,
                agent_id=agent_id,
                kind="TEST",
                passed=passed,
            )
        if artifact.type == "CODE_REVIEW":
            passed = _find_verdict(artifact.content, _REVIEW_VERDICTS)
            if passed is None:
                return None
            return QualityRecord(
                recorded_at=recorded_at,
                project_id=project_id,
                task_id=task_id,
                agent_id=agent_id,
                kind="REVIEW",
                passed=passed,
            )
        return None
    except Exception:
        return None


class MetricsService:
    """In-memory, thread-safe aggregation of runtime metrics and events.

    Implements both orchestrator write-side ports: ``record`` satisfies
    ``MetricsRecorder`` and ``publish`` satisfies ``EventPublisher``. One
    instance can be passed as both ``metrics=`` and ``events=`` to the
    orchestrator. All state is held in plain records so ``snapshot`` /
    ``restore`` can persist it alongside the execution store.

    Aggregation choices (kept deliberate, see README):

    * ``successRate`` for an agent is ``completed / total`` where ``total``
      is every recorded result for that agent.
    * There is no dashboard bucket for a ``REJECTED`` result, so rejected
      runs count in the ``failed`` bucket (and therefore against the
      success rate) rather than being silently dropped.
    * "Finished" rates used by daily buckets and project outcomes are
      ``completed / (completed + failed)``; running and cancelled work is
      excluded from those denominators.
    * Any rate with a zero denominator is ``0.0``.
    """

    def __init__(self, *, clock: Callable[[], datetime]) -> None:
        self._clock = clock
        self._lock = RLock()
        self._runs: list[AgentRunRecord] = []
        self._approvals: list[ApprovalRecord] = []
        self._quality: list[QualityRecord] = []
        self._events: list[ActivityEvent] = []

    # -- internal helpers -------------------------------------------------

    def _now(self) -> datetime:
        now = self._clock()
        if not isinstance(now, datetime):
            raise TypeError("Clock must return a datetime instance")
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Clock must return a timezone-aware datetime")
        return now

    @staticmethod
    def _require_aware(value: datetime, name: str) -> datetime:
        if not isinstance(value, datetime):
            raise TypeError(f"{name} must be a datetime instance")
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{name} must be a timezone-aware datetime")
        return value

    # -- MetricsRecorder port ---------------------------------------------

    def record(
        self,
        agent_id: str,
        result: AgentResult,
        *,
        run_id: str | None = None,
    ) -> None:
        """Record one agent result, deriving quality samples from artifacts."""
        with self._lock:
            recorded_at = self._now()
            project_id: str | None = None
            task_id: str | None = None
            for event in result.events:
                if project_id is None and event.project_id:
                    project_id = event.project_id
                if task_id is None and event.task_id:
                    task_id = event.task_id
            self._runs.append(
                AgentRunRecord(
                    recorded_at=recorded_at,
                    agent_id=agent_id,
                    request_id=result.request_id,
                    project_id=project_id,
                    task_id=task_id,
                    status=result.status,
                    duration_seconds=result.metrics.duration_seconds,
                    revision_count=result.metrics.revision_count,
                    attempt=result.metrics.attempt,
                    run_id=run_id,
                    prompt_tokens=result.metrics.prompt_tokens,
                    completion_tokens=result.metrics.completion_tokens,
                    model_calls=result.metrics.model_calls,
                )
            )
            for artifact in result.artifacts:
                sample = _artifact_sample(
                    artifact,
                    agent_id=agent_id,
                    project_id=project_id,
                    task_id=task_id,
                    recorded_at=recorded_at,
                )
                if sample is not None:
                    self._quality.append(sample)

    # -- EventPublisher port ----------------------------------------------

    def publish(self, event: ActivityEvent) -> None:
        """Store a copy of an activity event."""
        with self._lock:
            self._events.append(event.model_copy(deep=True))
            self._record_ai_decision_locked(event)

    def _record_ai_decision_locked(self, event: ActivityEvent) -> None:
        record = ai_decision_record(event)
        if record is not None:
            self._approvals.append(record)

    def events(self) -> list[ActivityEvent]:
        """Return copies of the stored events in chronological order."""
        with self._lock:
            ordered = sorted(self._events, key=lambda event: event.timestamp)
            return [event.model_copy(deep=True) for event in ordered]

    # -- Explicit samples ---------------------------------------------------

    def record_approval_decision(
        self,
        *,
        project_id: str,
        task_id: str | None,
        agent_id: str,
        decision: str,
        reviewer_kind: str = "HUMAN",
        at: datetime | None = None,
    ) -> None:
        """Record one decision; human rates count HUMAN records only."""
        if decision not in _DECISIONS:
            raise ValueError(f"decision must be one of {_DECISIONS}")
        if reviewer_kind not in ("HUMAN", "AI"):
            raise ValueError("reviewer_kind must be HUMAN or AI")
        with self._lock:
            recorded_at = self._now() if at is None else self._require_aware(at, "at")
            self._approvals.append(
                ApprovalRecord.model_validate(
                    {
                        "recorded_at": recorded_at,
                        "project_id": project_id,
                        "task_id": task_id,
                        "agent_id": agent_id,
                        "decision": decision,
                        "reviewer_kind": reviewer_kind,
                    }
                )
            )

    def record_quality(
        self,
        *,
        project_id: str,
        task_id: str | None,
        agent_id: str,
        kind: str,
        passed: bool,
    ) -> None:
        """Record an explicit TEST, CI, or REVIEW pass/fail sample."""
        if kind not in _QUALITY_KINDS:
            raise ValueError(f"kind must be one of {_QUALITY_KINDS}")
        with self._lock:
            self._quality.append(
                QualityRecord.model_validate(
                    {
                        "recorded_at": self._now(),
                        "project_id": project_id,
                        "task_id": task_id,
                        "agent_id": agent_id,
                        "kind": kind,
                        "passed": passed,
                    }
                )
            )

    # -- Aggregation helpers (lock held by callers) -------------------------

    def _quality_rate_locked(self, records: list[QualityRecord], kind: str) -> float:
        samples = [record for record in records if record.kind == kind]
        return _rate(sum(1 for record in samples if record.passed), len(samples))

    def _agent_metrics_locked(self, agent_id: str) -> dict[str, Any]:
        runs = [run for run in self._runs if run.agent_id == agent_id]
        approvals = [item for item in self._approvals if item.agent_id == agent_id]
        quality = [item for item in self._quality if item.agent_id == agent_id]
        return agent_metrics_view(
            runs,
            approvals,
            test_pass_rate=self._quality_rate_locked(quality, "TEST"),
            ci_pass_rate=self._quality_rate_locked(quality, "CI"),
        )

    # -- Dashboard-shaped getters -------------------------------------------

    def agent_metrics(self, agent_id: str) -> dict[str, Any]:
        """Return the dashboard ``AgentMetrics`` shape for one agent."""
        with self._lock:
            return self._agent_metrics_locked(agent_id)

    def run_metrics(self, run_id: str) -> dict[str, Any]:
        """Token/call totals for one workflow run, across its agents."""
        with self._lock:
            runs = [run for run in self._runs if run.run_id == run_id]
            return {
                "runId": run_id,
                "executions": len(runs),
                "promptTokens": sum(run.prompt_tokens for run in runs),
                "completionTokens": sum(run.completion_tokens for run in runs),
                "modelCalls": sum(run.model_calls for run in runs),
            }

    def all_agent_metrics(self) -> dict[str, dict[str, Any]]:
        """Return ``AgentMetrics`` for every agent with any recorded data."""
        with self._lock:
            agent_ids = (
                {run.agent_id for run in self._runs}
                | {item.agent_id for item in self._approvals}
                | {item.agent_id for item in self._quality}
            )
            return {
                agent_id: self._agent_metrics_locked(agent_id) for agent_id in sorted(agent_ids)
            }

    def overview(self) -> dict[str, Any]:
        """Return the dashboard ``MetricsOverview`` shape."""
        with self._lock:
            runs_by_date: dict[str, list[AgentRunRecord]] = {}
            for run in self._runs:
                runs_by_date.setdefault(run.recorded_at.date().isoformat(), []).append(run)
            daily = []
            for date in sorted(runs_by_date):
                day_runs = runs_by_date[date]
                completed = sum(1 for run in day_runs if run.status == "SUCCESS")
                failed = sum(1 for run in day_runs if run.status in _FAILED_STATUSES)
                daily.append(
                    {
                        "date": date,
                        "completed": completed,
                        "failed": failed,
                        "successRate": _rate(completed, completed + failed),
                        "avgDurationSec": _mean([run.duration_seconds for run in day_runs]),
                    }
                )

            human = human_section(self._approvals, self._runs)

            quality_dates = sorted(
                {item.recorded_at.date().isoformat() for item in self._quality} | set(runs_by_date),
            )
            quality_daily = []
            for date in quality_dates:
                day_quality = [
                    item for item in self._quality if item.recorded_at.date().isoformat() == date
                ]
                day_runs = runs_by_date.get(date, [])
                quality_daily.append(
                    {
                        "date": date,
                        "testPassRate": self._quality_rate_locked(day_quality, "TEST"),
                        "ciPassRate": self._quality_rate_locked(day_quality, "CI"),
                        "reworkRate": _rate(
                            sum(1 for run in day_runs if run.revision_count > 0),
                            len(day_runs),
                        ),
                    }
                )
            review_samples = [item for item in self._quality if item.kind == "REVIEW"]
            quality = {
                "codeReviewRejectionRate": _rate(
                    sum(1 for item in review_samples if not item.passed),
                    len(review_samples),
                ),
                "testPassRate": self._quality_rate_locked(self._quality, "TEST"),
                "ciPassRate": self._quality_rate_locked(self._quality, "CI"),
                "reworkRate": _rate(
                    sum(1 for run in self._runs if run.revision_count > 0),
                    len(self._runs),
                ),
                "daily": quality_daily,
            }

            agents = [
                {
                    "agentId": agent_id,
                    "name": agent_id,
                    "successRate": metrics["successRate"],
                    "avgDurationSec": metrics["avgDurationSec"],
                    "avgRevisions": metrics["avgRevisions"],
                    "humanApprovalRate": metrics["humanApprovalRate"],
                    "healthScore": metrics["healthScore"],
                }
                for agent_id, metrics in self.all_agent_metrics().items()
            ]
            return {
                "daily": daily,
                "human": human,
                "quality": quality,
                "agents": agents,
                "aiReview": ai_review_metrics(self._events),
            }

    def project_outcomes(self, project_id: str) -> dict[str, Any]:
        """Return run counts for one project, for composing ``ProjectMetrics``.

        ``successRate`` is ``completed / (completed + failed)`` over finished
        runs of the project; running/cancelled runs are excluded from the
        denominator. Results whose project cannot be derived (a result with
        no events) are not attributed to any project.
        """
        with self._lock:
            runs = [run for run in self._runs if run.project_id == project_id]
            completed = sum(1 for run in runs if run.status == "SUCCESS")
            failed = sum(1 for run in runs if run.status in _FAILED_STATUSES)
            return {
                "running": sum(1 for run in runs if run.status == "WAITING"),
                "completed": completed,
                "failed": failed,
                "successRate": _rate(completed, completed + failed),
            }

    # -- Persistence ---------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-safe snapshot of every record held by the service."""
        with self._lock:
            return {
                "version": _SNAPSHOT_VERSION,
                "runs": [run.model_dump(mode="json", by_alias=True) for run in self._runs],
                "approvals": [
                    item.model_dump(mode="json", by_alias=True) for item in self._approvals
                ],
                "quality": [item.model_dump(mode="json", by_alias=True) for item in self._quality],
                "events": [event.model_dump(mode="json", by_alias=True) for event in self._events],
            }

    def load(self, data: Mapping[str, Any]) -> None:
        """Replace the service state with a previously taken snapshot."""
        if not isinstance(data, Mapping):
            raise TypeError("Snapshot data must be a mapping")
        version = data.get("version", _SNAPSHOT_VERSION)
        if version != _SNAPSHOT_VERSION:
            raise ValueError(f"Unsupported metrics snapshot version: {version!r}")
        runs = [AgentRunRecord.model_validate(item) for item in data.get("runs", [])]
        approvals = [ApprovalRecord.model_validate(item) for item in data.get("approvals", [])]
        quality = [QualityRecord.model_validate(item) for item in data.get("quality", [])]
        events = [ActivityEvent.model_validate(item) for item in data.get("events", [])]
        with self._lock:
            self._runs = runs
            self._approvals = approvals
            self._quality = quality
            self._events = events

    @classmethod
    def restore(
        cls,
        data: Mapping[str, Any],
        *,
        clock: Callable[[], datetime],
    ) -> MetricsService:
        """Build a new service pre-loaded from a snapshot."""
        service = cls(clock=clock)
        service.load(data)
        return service
