from __future__ import annotations

from datetime import timedelta

import pytest

from asf.approval.errors import ApprovalError
from asf.approval.models import ApprovalPolicy
from asf.configuration.platform import NotificationChannel
from asf.integrations.teams.approval import TeamsAction, TeamsActor, TeamsApprovals
from asf.integrations.teams.config import TeamsConfig
from tests.unit.test_orchestrator import NOW, make_engine, start


def config():
    return TeamsConfig(
        tenant_id="00000000-0000-0000-0000-000000000002",
        team_id="00000000-0000-0000-0000-000000000003",
        channel_id="channel",
        workflow_host="example.environment.api.powerplatform.com",
        credentials={"env": "ASF_TEAMS_WORKFLOW_URL"},
        callback_secret={"env": "ASF_TEAMS_CALLBACK_SECRET"},
        reviewers={
            "00000000-0000-0000-0000-000000000004": "reviewer",
            "00000000-0000-0000-0000-000000000005": "second",
        },
    )


def actor():
    settings = config()
    return TeamsActor(
        tenant_id=settings.tenant_id,
        team_id=settings.team_id,
        channel_id=settings.channel_id,
        object_id=next(iter(settings.reviewers)),
    )


def setup():
    engine, _, _, repo = make_engine(approval=True)
    run = engine.tick(start(engine).id)
    return TeamsApprovals(config(), engine), run, repo


def test_expected_approval_rejects_stale_card_without_decision():
    engine, _, _, approvals = make_engine(approval=True)
    run = engine.tick(start(engine).id)
    with pytest.raises(ApprovalError, match="current approval"):
        engine.decide(
            run.id,
            reviewer="reviewer",
            decision="APPROVED",
            expected_approval_id="stale",
        )
    assert engine.get(run.id).approval_id == run.approval_id
    assert approvals.get(run.approval_id).status == "PENDING"


def test_expected_approval_allows_current_card_and_rejects_replay():
    engine, _, _, _ = make_engine(approval=True)
    run = engine.tick(start(engine).id)
    decided = engine.decide(
        run.id,
        reviewer="reviewer",
        decision="APPROVED",
        expected_approval_id=run.approval_id,
    )
    assert decided.state.stage == "PLAN"
    with pytest.raises(ApprovalError, match="current approval"):
        engine.decide(
            run.id,
            reviewer="reviewer",
            decision="APPROVED",
            expected_approval_id=run.approval_id,
        )


@pytest.mark.parametrize(
    "decision,stage",
    [
        ("APPROVED", "PLAN"),
        ("REJECTED", "SPEC_DRAFT"),
        ("REQUEST_CHANGES", "SPEC_DRAFT"),
    ],
)
def test_teams_decisions_reuse_approval_rules(decision, stage):
    service, run, repo = setup()
    result = service.decide(
        actor(),
        TeamsAction(
            run_id=run.id,
            approval_id=run.approval_id,
            decision=decision,
            comment="Please revise",
        ),
    )
    assert result.state.stage == stage
    decisions = repo.list_decisions(run.approval_id)
    assert len(decisions) == 1
    assert decisions[0].reviewer == "reviewer"


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", "00000000-0000-0000-0000-000000000099"),
        ("team_id", "00000000-0000-0000-0000-000000000099"),
        ("object_id", "00000000-0000-0000-0000-000000000099"),
        ("channel_id", "other"),
    ],
)
def test_teams_rejects_wrong_binding_before_decision(field, value):
    service, run, repo = setup()
    invalid = TeamsActor.model_validate({**actor().model_dump(), field: value})
    with pytest.raises(ApprovalError) as caught:
        service.decide(
            invalid,
            TeamsAction(
                run_id=run.id,
                approval_id=run.approval_id,
                decision="APPROVED",
            ),
        )
    assert caught.value.code == "APPROVAL_NOT_AUTHORIZED"
    assert repo.list_decisions(run.approval_id) == []


@pytest.mark.parametrize("decision", ["REJECTED", "REQUEST_CHANGES"])
def test_teams_negative_decision_requires_comment(decision):
    service, run, repo = setup()
    with pytest.raises(ApprovalError) as caught:
        service.decide(
            actor(),
            TeamsAction(
                run_id=run.id,
                approval_id=run.approval_id,
                decision=decision,
                comment=" ",
            ),
        )
    assert caught.value.code == "VALIDATION_FAILED"
    assert repo.list_decisions(run.approval_id) == []


def test_teams_quorum_and_duplicate_reviewer():
    engine, _, _, repo = make_engine(approval=True)
    engine._approval_policy = ApprovalPolicy(reviewers=["reviewer", "second"], min_approvals=2)
    run = engine.tick(start(engine).id)
    service = TeamsApprovals(config(), engine)
    action = TeamsAction(run_id=run.id, approval_id=run.approval_id, decision="APPROVED")
    assert service.decide(actor(), action).state.stage == "SPEC_REVIEW"
    with pytest.raises(ApprovalError) as caught:
        service.decide(actor(), action)
    assert caught.value.code == "APPROVAL_ALREADY_DECIDED"
    second = TeamsActor.model_validate(
        {
            **actor().model_dump(),
            "object_id": "00000000-0000-0000-0000-000000000005",
        }
    )
    assert service.decide(second, action).state.stage == "PLAN"
    assert len(repo.list_decisions(run.approval_id)) == 2


def test_teams_action_cannot_supply_reviewer():
    with pytest.raises(ValueError):
        TeamsAction(
            run_id="run",
            approval_id="approval",
            decision="APPROVED",
            reviewer="admin",
        )


def test_teams_config_from_notification_channel():
    expected = config()
    channel = NotificationChannel(
        name="approvals",
        type="teams-workflow",
        credentials=expected.credentials,
        settings=expected.model_dump(exclude={"credentials"}),
    )
    assert TeamsConfig.from_channel(channel) == expected


@pytest.mark.parametrize(
    "updates",
    [
        {"endpoint": "https://example.com"},
        {"type": "webhook"},
        {"credentials": None},
    ],
)
def test_teams_config_rejects_webhook_configuration(updates):
    base = dict(
        name="approvals",
        type="teams-workflow",
        credentials=config().credentials,
        settings=config().model_dump(exclude={"credentials"}),
    )
    with pytest.raises(ValueError):
        TeamsConfig.from_channel(NotificationChannel(**{**base, **updates}))


def test_teams_config_rejects_identity_aliases():
    values = config().model_dump()
    values["reviewers"] = {key: "reviewer" for key in values["reviewers"]}
    with pytest.raises(ValueError, match="distinct"):
        TeamsConfig.model_validate(values)


@pytest.mark.parametrize("untrusted", ["reviewer", "objectId", "tenantId", "conversationId"])
def test_teams_action_rejects_client_supplied_identity(untrusted):
    with pytest.raises(ValueError):
        TeamsAction.model_validate(
            {
                "runId": "run",
                "approvalId": "approval",
                "decision": "APPROVED",
                untrusted: "spoofed",
            }
        )


def test_expired_teams_card_fails_without_recording_decision():
    engine, _, _, repo = make_engine(approval=True)
    engine._approval_policy = ApprovalPolicy(reviewers=["reviewer"], expires_in_seconds=1)
    run = engine.tick(start(engine).id)
    service = TeamsApprovals(config(), engine)
    engine._clock = lambda: NOW + timedelta(seconds=2)
    with pytest.raises(ApprovalError) as caught:
        service.decide(
            actor(),
            TeamsAction(
                run_id=run.id,
                approval_id=run.approval_id,
                decision="APPROVED",
            ),
        )
    assert caught.value.code == "APPROVAL_EXPIRED"
    assert engine.get(run.id).state.stage == "FAILED"
    assert repo.list_decisions(run.approval_id) == []
    with pytest.raises(ApprovalError):
        service.pending(run.id)


def test_old_card_cannot_approve_revised_artifact():
    service, first, repo = setup()
    service.decide(
        actor(),
        TeamsAction(
            run_id=first.id,
            approval_id=first.approval_id,
            decision="REJECTED",
            comment="Please revise",
        ),
    )
    revised = service.engine.tick(first.id)
    assert revised.approval_id != first.approval_id
    with pytest.raises(ApprovalError) as caught:
        service.decide(
            actor(),
            TeamsAction(
                run_id=first.id,
                approval_id=first.approval_id,
                decision="APPROVED",
            ),
        )
    assert caught.value.code == "APPROVAL_ALREADY_DECIDED"
    assert repo.list_decisions(revised.approval_id) == []
    assert service.pending(first.id).id == revised.approval_id
