"""MetricsService aggregation, parsing, persistence, and concurrency tests."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from asf.contracts.models import ActivityEvent, AgentResult, Artifact, RunMetrics
from asf.evaluation import MetricsService

DAY1 = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)
DAY2 = datetime(2026, 11, 3, 9, 0, tzinfo=timezone.utc)


class MutableClock:
    def __init__(self, now: datetime = DAY1) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def make_event(
    event_id: str,
    *,
    project_id: str = "project-1",
    task_id: str | None = "task-1",
    at: datetime = DAY1,
    agent_id: str | None = None,
) -> ActivityEvent:
    return ActivityEvent(
        id=event_id,
        timestamp=at,
        project_id=project_id,
        task_id=task_id,
        agent_id=agent_id,
        event_type="TEST",
        message=f"event {event_id}",
    )


def make_artifact(artifact_type: str, content: object, artifact_id: str = "art-1") -> Artifact:
    return Artifact(
        id=artifact_id,
        type=artifact_type,
        name=artifact_type,
        version="1",
        content=content,
        created_by="agent-test",
        created_at=DAY1,
    )


def make_result(
    *,
    agent_id: str = "agent-spec",
    status: str = "SUCCESS",
    duration: float = 10.0,
    revisions: int = 0,
    request_id: str = "req-1",
    artifacts: list[Artifact] | None = None,
    events: list[ActivityEvent] | None = None,
) -> AgentResult:
    return AgentResult(
        request_id=request_id,
        agent_id=agent_id,
        status=status,  # type: ignore[arg-type]
        artifacts=artifacts or [],
        events=events or [],
        metrics=RunMetrics(
            duration_seconds=duration,
            revision_count=revisions,
            attempt=1,
        ),
    )


def test_empty_service_returns_zeroed_dashboard_shapes() -> None:
    service = MetricsService(clock=MutableClock())

    metrics = service.agent_metrics("agent-unknown")
    assert metrics["total"] == 0
    assert metrics["completed"] == 0
    assert metrics["successRate"] == 0.0
    assert metrics["avgDurationSec"] == 0.0
    assert metrics["avgRevisions"] == 0.0
    assert metrics["humanApprovalRate"] == 0.0
    assert metrics["testPassRate"] == 0.0
    assert metrics["ciPassRate"] == 0.0
    # Dashboard formula at avgRevisions == 0: the revision term alone is
    # 0.15 * (1 - (0 - 1) / 3) = 0.20, so an empty agent scores 20, not 0.
    assert metrics["healthScore"] == 20
    assert service.all_agent_metrics() == {}

    overview = service.overview()
    assert overview["daily"] == []
    assert overview["human"]["approvalRate"] == 0.0
    assert overview["human"]["avgApprovalMinutes"] == 0.0
    assert overview["quality"]["reworkRate"] == 0.0
    assert overview["agents"] == []
    assert service.project_outcomes("project-1") == {
        "running": 0,
        "completed": 0,
        "failed": 0,
        "successRate": 0.0,
    }
    assert service.events() == []


def test_aggregation_math_and_health_formula() -> None:
    service = MetricsService(clock=MutableClock())
    for index, (status, duration) in enumerate(
        [
            ("SUCCESS", 10.0),
            ("SUCCESS", 20.0),
            ("FAILED", 30.0),
            ("REJECTED", 40.0),
        ]
    ):
        service.record(
            "agent-spec",
            make_result(
                status=status,
                duration=duration,
                revisions=1,
                request_id=f"req-{index}",
            ),
        )
    service.record_approval_decision(
        project_id="project-1",
        task_id="task-1",
        agent_id="agent-spec",
        decision="APPROVED",
    )
    service.record_approval_decision(
        project_id="project-1",
        task_id="task-1",
        agent_id="agent-spec",
        decision="REJECTED",
    )
    service.record_quality(
        project_id="project-1",
        task_id="task-1",
        agent_id="agent-spec",
        kind="TEST",
        passed=True,
    )
    service.record_quality(
        project_id="project-1",
        task_id="task-1",
        agent_id="agent-spec",
        kind="TEST",
        passed=False,
    )
    for passed in (True, True, False, False):
        service.record_quality(
            project_id="project-1",
            task_id="task-1",
            agent_id="agent-spec",
            kind="CI",
            passed=passed,
        )

    metrics = service.agent_metrics("agent-spec")
    assert metrics["total"] == 4
    assert metrics["completed"] == 2
    assert metrics["running"] == 0
    # REJECTED has no dashboard bucket of its own: it counts as failed.
    assert metrics["failed"] == 2
    assert metrics["cancelled"] == 0
    assert metrics["successRate"] == pytest.approx(0.5)
    assert metrics["avgDurationSec"] == pytest.approx(25.0)
    assert metrics["avgRevisions"] == pytest.approx(1.0)
    assert metrics["humanApprovalRate"] == pytest.approx(0.5)
    assert metrics["testPassRate"] == pytest.approx(0.5)
    assert metrics["ciPassRate"] == pytest.approx(0.5)
    # Dashboard weights: .30*.5 + .20*.5 + .20*.5 + .15*.5 + .15*1.0 = .575
    # in decimal, but in IEEE-754 doubles (which both the dashboard's
    # Math.round and this service compute with) the product is
    # 57.49999999999999, so the dashboard formula itself yields 57 here.
    assert metrics["healthScore"] == 57


def test_health_formula_perfect_and_zero_rates() -> None:
    service = MetricsService(clock=MutableClock())
    service.record("agent-spec", make_result(revisions=1))
    service.record_approval_decision(
        project_id="project-1",
        task_id="task-1",
        agent_id="agent-spec",
        decision="APPROVED",
    )
    service.record_quality(
        project_id="project-1",
        task_id="task-1",
        agent_id="agent-spec",
        kind="TEST",
        passed=True,
    )
    service.record_quality(
        project_id="project-1",
        task_id="task-1",
        agent_id="agent-spec",
        kind="CI",
        passed=True,
    )
    # Every rate 1.0 and avgRevisions 1.0 (revision score 1.0): weights sum to 1.
    assert service.agent_metrics("agent-spec")["healthScore"] == 100

    failing = MetricsService(clock=MutableClock())
    failing.record("agent-spec", make_result(status="FAILED", revisions=4))
    metrics = failing.agent_metrics("agent-spec")
    # Revision score at avgRevisions 4 is max(0, 1 - 3/3) = 0; all rates are 0.
    assert metrics["healthScore"] == 0


def test_status_mapping_for_waiting_and_cancelled() -> None:
    service = MetricsService(clock=MutableClock())
    service.record(
        "agent-plan",
        make_result(
            agent_id="agent-plan",
            status="WAITING",
            request_id="req-w",
        ),
    )
    service.record(
        "agent-plan",
        make_result(
            agent_id="agent-plan",
            status="CANCELLED",
            request_id="req-c",
        ),
    )

    metrics = service.agent_metrics("agent-plan")
    assert metrics["total"] == 2
    assert metrics["running"] == 1
    assert metrics["cancelled"] == 1
    assert metrics["failed"] == 0
    assert metrics["successRate"] == 0.0


def test_test_and_review_verdicts_are_parsed_from_artifacts() -> None:
    service = MetricsService(clock=MutableClock())
    pass_report = make_artifact(
        "TEST_REPORT",
        {
            "format": "json",
            "report": {"verdict": "PASS", "commands": [], "summary": "PASS: 1/1 commands passed"},
            "text": "PASS",
        },
        "report-pass",
    )
    fail_report = make_artifact(
        "TEST_REPORT",
        {
            "format": "json",
            "report": {"verdict": "FAIL", "commands": [], "summary": "FAIL: 0/1 commands passed"},
            "text": "FAIL",
        },
        "report-fail",
    )
    service.record(
        "agent-test",
        make_result(
            agent_id="agent-test",
            request_id="req-pass",
            artifacts=[pass_report],
        ),
    )
    service.record(
        "agent-test",
        make_result(
            agent_id="agent-test",
            status="FAILED",
            request_id="req-fail",
            artifacts=[fail_report],
        ),
    )
    assert service.agent_metrics("agent-test")["testPassRate"] == pytest.approx(0.5)
    assert service.overview()["quality"]["testPassRate"] == pytest.approx(0.5)

    approve_review = make_artifact(
        "CODE_REVIEW",
        {
            "format": "json",
            "review": {"findings": [], "verdict": "APPROVE"},
            "text": "# CODE_REVIEW",
        },
        "review-approve",
    )
    changes_review = make_artifact(
        "CODE_REVIEW",
        {
            "format": "json",
            "review": {"findings": [], "verdict": "CHANGES_REQUESTED"},
            "text": "# CODE_REVIEW",
        },
        "review-changes",
    )
    service.record(
        "agent-review",
        make_result(
            agent_id="agent-review",
            request_id="req-approve",
            artifacts=[approve_review],
        ),
    )
    service.record(
        "agent-review",
        make_result(
            agent_id="agent-review",
            request_id="req-changes",
            artifacts=[changes_review],
        ),
    )
    assert service.overview()["quality"]["codeReviewRejectionRate"] == pytest.approx(0.5)


def test_unknown_artifact_shapes_are_ignored_never_raise() -> None:
    service = MetricsService(clock=MutableClock())
    weird = [
        make_artifact("TEST_REPORT", {"report": {"verdict": "MAYBE"}}, "w-1"),
        make_artifact("TEST_REPORT", {"unexpected": [1, 2, 3]}, "w-2"),
        make_artifact("TEST_REPORT", "not json at all", "w-3"),
        make_artifact("CODE_REVIEW", ["verdict", "APPROVE"], "w-4"),
        make_artifact("SPEC", {"verdict": "PASS"}, "w-5"),
    ]
    service.record(
        "agent-test",
        make_result(
            agent_id="agent-test",
            request_id="req-weird",
            artifacts=weird,
        ),
    )

    metrics = service.agent_metrics("agent-test")
    assert metrics["total"] == 1
    assert metrics["testPassRate"] == 0.0
    assert service.overview()["quality"]["codeReviewRejectionRate"] == 0.0


def test_direct_top_level_and_json_string_verdicts_are_parsed() -> None:
    service = MetricsService(clock=MutableClock())
    service.record(
        "agent-test",
        make_result(
            agent_id="agent-test",
            request_id="req-direct",
            artifacts=[make_artifact("TEST_REPORT", {"verdict": "PASS"}, "d-1")],
        ),
    )
    service.record(
        "agent-test",
        make_result(
            agent_id="agent-test",
            request_id="req-json",
            artifacts=[
                make_artifact(
                    "TEST_REPORT",
                    json.dumps({"report": {"verdict": "FAIL"}}),
                    "d-2",
                )
            ],
        ),
    )
    assert service.agent_metrics("agent-test")["testPassRate"] == pytest.approx(0.5)


def test_approval_rates_and_overview_human_section() -> None:
    service = MetricsService(clock=MutableClock())
    for decision in ("APPROVED", "REJECTED", "REQUEST_CHANGES"):
        service.record_approval_decision(
            project_id="project-1",
            task_id="task-1",
            agent_id="agent-spec",
            decision=decision,
        )
    service.record("agent-spec", make_result(revisions=2))

    human = service.overview()["human"]
    assert human["approvalRate"] == pytest.approx(1 / 3)
    assert human["rejectionRate"] == pytest.approx(2 / 3)
    assert human["avgRevisions"] == pytest.approx(2.0)
    assert human["avgApprovalMinutes"] == 0.0
    assert human["daily"] == [
        {
            "date": DAY1.date().isoformat(),
            "approvalRate": pytest.approx(1 / 3),
            "rejectionRate": pytest.approx(2 / 3),
        }
    ]
    assert service.agent_metrics("agent-spec")["humanApprovalRate"] == pytest.approx(1 / 3)


def test_invalid_decision_kind_and_naive_times_are_rejected() -> None:
    service = MetricsService(clock=MutableClock())
    with pytest.raises(ValueError):
        service.record_approval_decision(
            project_id="project-1",
            task_id=None,
            agent_id="agent-spec",
            decision="MAYBE",
        )
    with pytest.raises(ValueError):
        service.record_quality(
            project_id="project-1",
            task_id=None,
            agent_id="agent-spec",
            kind="LINT",
            passed=True,
        )
    with pytest.raises(ValueError):
        service.record_approval_decision(
            project_id="project-1",
            task_id=None,
            agent_id="agent-spec",
            decision="APPROVED",
            at=datetime(2026, 11, 2, 9, 0),
        )
    naive = MetricsService(clock=lambda: datetime(2026, 11, 2, 9, 0))
    with pytest.raises(ValueError):
        naive.record("agent-spec", make_result())


def test_overview_daily_buckets_rework_and_agents() -> None:
    clock = MutableClock()
    service = MetricsService(clock=clock)
    service.record(
        "agent-spec",
        make_result(
            status="SUCCESS",
            duration=10.0,
            revisions=0,
            request_id="req-1",
        ),
    )
    service.record(
        "agent-spec",
        make_result(
            status="FAILED",
            duration=30.0,
            revisions=2,
            request_id="req-2",
        ),
    )
    service.record_quality(
        project_id="project-1",
        task_id="task-1",
        agent_id="agent-test",
        kind="TEST",
        passed=True,
    )
    service.record_quality(
        project_id="project-1",
        task_id="task-1",
        agent_id="agent-test",
        kind="CI",
        passed=False,
    )
    clock.now = DAY2
    service.record(
        "agent-spec",
        make_result(
            status="SUCCESS",
            duration=20.0,
            revisions=0,
            request_id="req-3",
        ),
    )

    overview = service.overview()
    assert overview["daily"] == [
        {
            "date": DAY1.date().isoformat(),
            "completed": 1,
            "failed": 1,
            "successRate": pytest.approx(0.5),
            "avgDurationSec": pytest.approx(20.0),
        },
        {
            "date": DAY2.date().isoformat(),
            "completed": 1,
            "failed": 0,
            "successRate": pytest.approx(1.0),
            "avgDurationSec": pytest.approx(20.0),
        },
    ]
    quality = overview["quality"]
    assert quality["testPassRate"] == pytest.approx(1.0)
    assert quality["ciPassRate"] == pytest.approx(0.0)
    assert quality["reworkRate"] == pytest.approx(1 / 3)
    assert quality["daily"][0] == {
        "date": DAY1.date().isoformat(),
        "testPassRate": pytest.approx(1.0),
        "ciPassRate": pytest.approx(0.0),
        "reworkRate": pytest.approx(0.5),
    }
    assert quality["daily"][1]["reworkRate"] == pytest.approx(0.0)

    rows = {row["agentId"]: row for row in overview["agents"]}
    assert set(rows) == {"agent-spec", "agent-test"}
    assert rows["agent-spec"]["name"] == "agent-spec"
    assert rows["agent-spec"]["successRate"] == pytest.approx(2 / 3)
    assert (
        rows["agent-test"]["healthScore"]
        == service.agent_metrics(
            "agent-test",
        )["healthScore"]
    )


def test_project_outcomes_uses_events_for_attribution() -> None:
    service = MetricsService(clock=MutableClock())

    def attributed(status: str, request_id: str, project_id: str) -> AgentResult:
        return make_result(
            status=status,
            request_id=request_id,
            events=[make_event(f"ev-{request_id}", project_id=project_id)],
        )

    service.record("agent-spec", attributed("SUCCESS", "p1-a", "project-1"))
    service.record("agent-spec", attributed("FAILED", "p1-b", "project-1"))
    service.record("agent-spec", attributed("WAITING", "p1-c", "project-1"))
    service.record("agent-spec", attributed("REJECTED", "p1-d", "project-1"))
    service.record("agent-spec", attributed("SUCCESS", "p2-a", "project-2"))
    # No events: recorded, but not attributable to any project.
    service.record("agent-spec", make_result(request_id="orphan"))

    assert service.project_outcomes("project-1") == {
        "running": 1,
        "completed": 1,
        "failed": 2,
        "successRate": pytest.approx(1 / 3),
    }
    assert service.project_outcomes("project-2") == {
        "running": 0,
        "completed": 1,
        "failed": 0,
        "successRate": pytest.approx(1.0),
    }
    assert service.project_outcomes("project-missing") == {
        "running": 0,
        "completed": 0,
        "failed": 0,
        "successRate": 0.0,
    }


def test_events_are_copied_and_chronological() -> None:
    service = MetricsService(clock=MutableClock())
    later = make_event("ev-late", at=DAY1 + timedelta(hours=2))
    earlier = make_event("ev-early", at=DAY1)
    service.publish(later)
    service.publish(earlier)

    events = service.events()
    assert [event.id for event in events] == ["ev-early", "ev-late"]
    events.clear()
    assert len(service.events()) == 2


def test_getters_return_fresh_dicts() -> None:
    service = MetricsService(clock=MutableClock())
    service.record("agent-spec", make_result())

    first = service.agent_metrics("agent-spec")
    first["total"] = 999
    assert service.agent_metrics("agent-spec")["total"] == 1

    overview = service.overview()
    overview["human"]["approvalRate"] = 9.9
    assert service.overview()["human"]["approvalRate"] == 0.0


def test_snapshot_round_trip_is_json_safe_and_restores_everything() -> None:
    clock = MutableClock()
    service = MetricsService(clock=clock)
    service.record(
        "agent-test",
        make_result(
            agent_id="agent-test",
            request_id="req-1",
            revisions=1,
            artifacts=[make_artifact("TEST_REPORT", {"report": {"verdict": "PASS"}})],
            events=[make_event("ev-1")],
        ),
    )
    service.record_approval_decision(
        project_id="project-1",
        task_id="task-1",
        agent_id="agent-test",
        decision="APPROVED",
    )
    service.record_quality(
        project_id="project-1",
        task_id="task-1",
        agent_id="agent-ci",
        kind="CI",
        passed=False,
    )
    service.publish(make_event("ev-1"))
    service.publish(make_event("ev-2"))

    snapshot = service.snapshot()
    encoded = json.dumps(snapshot)
    restored = MetricsService.restore(json.loads(encoded), clock=MutableClock())

    assert restored.agent_metrics("agent-test") == service.agent_metrics("agent-test")
    assert restored.agent_metrics("agent-ci") == service.agent_metrics("agent-ci")
    assert restored.overview() == service.overview()
    assert restored.project_outcomes("project-1") == service.project_outcomes("project-1")
    assert [event.id for event in restored.events()] == ["ev-1", "ev-2"]
    assert restored.snapshot() == snapshot

    loaded = MetricsService(clock=MutableClock())
    loaded.load(snapshot)
    assert loaded.agent_metrics("agent-test") == service.agent_metrics("agent-test")

    with pytest.raises(ValueError):
        MetricsService.restore({"version": 99}, clock=MutableClock())


def test_thread_smoke_concurrent_recording() -> None:
    service = MetricsService(clock=MutableClock())
    per_worker = 25
    workers = 8

    def work(worker: int) -> None:
        for index in range(per_worker):
            service.record(
                "agent-spec",
                make_result(
                    request_id=f"req-{worker}-{index}",
                    duration=1.0,
                ),
            )
            service.publish(make_event(f"ev-{worker}-{index}"))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(work, range(workers)))

    assert service.agent_metrics("agent-spec")["total"] == workers * per_worker
    assert len(service.events()) == workers * per_worker
