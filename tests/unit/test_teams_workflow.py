from __future__ import annotations

import asyncio
import json
import logging
import time
import urllib.request
from datetime import timedelta
from urllib.error import URLError

import httpx
import pytest

from asf.approval.errors import ApprovalError
from asf.approval.models import ApprovalPolicy
from asf.integrations.gemini import UrlLibTransport, _ResponseTooLargeError
from asf.integrations.teams.demo import DemoModels, demo_engine
from asf.integrations.teams.workflow import (
    TeamsDeliveryError,
    TeamsWorkflow,
    WorkflowDecision,
    create_app,
)
from asf.storage.memory import InMemoryStore
from tests.unit._fake_secrets import fake_secret
from tests.unit.test_orchestrator import make_engine, start
from tests.unit.test_teams_approval import actor, config, setup


class FakeTransport:
    def __init__(self, *, status=202, error=None):
        self.calls = []
        self.status = status
        self.error = error

    def post(self, url, *, headers, body, timeout_seconds, max_response_bytes):
        self.calls.append((url, headers, json.loads(body), timeout_seconds, max_response_bytes))
        if self.error is not None:
            raise self.error
        return self.status, {}, b""


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Unexpected network call during workflow tests")

    monkeypatch.setattr(UrlLibTransport, "post", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)


@pytest.fixture
def credentials(monkeypatch):
    url = f"https://{config().workflow_host}/trigger?signature=" + "fake-" + "x" * 20
    secret = fake_secret("aq") + ("x" * 12)
    monkeypatch.setenv("ASF_TEAMS_WORKFLOW_URL", url)
    monkeypatch.setenv("ASF_TEAMS_CALLBACK_SECRET", secret)
    return url, secret


def managed(credentials, *, transport=None):
    service, run, repo = setup()
    flow = TeamsWorkflow(config(), service.engine, transport=transport or FakeTransport())
    return flow, run, repo


def payload(run, *, decision="APPROVED", comment=""):
    return {
        "actor": actor().model_dump(mode="json", by_alias=True),
        "action": {
            "runId": run.id,
            "approvalId": run.approval_id,
            "decision": decision,
            "comment": comment,
        },
    }


async def post(app, data, secret, *, raw=None):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://local",
    ) as client:
        return await client.post(
            "/api/teams/decisions",
            headers={"Authorization": "Bearer " + secret},
            **({"json": data} if raw is None else {"content": raw}),
        )


def test_workflow_posts_full_spec_with_submit_and_required_reject_comment(credentials):
    flow, run, _ = managed(credentials)
    flow.send_approval(run.id)
    url, headers, body, timeout, size = flow._transport.calls[0]
    assert url == credentials[0]
    assert headers == {"Content-Type": "application/json"}
    assert timeout == 30
    assert size == 4096
    card = body["card"]
    assert card["version"] == "1.3"
    assert (
        card["body"][2]["text"]
        == (flow.approvals.engine.get(run.id).artifacts["SPEC"].content["text"])
    )
    assert card["actions"][0]["type"] == "Action.Submit"
    assert card["actions"][0]["data"]["decision"] == "APPROVED"
    rejection = card["actions"][1]["card"]
    assert rejection["body"][0]["isRequired"] is True
    assert rejection["body"][0]["id"] == "rejectComment"
    assert rejection["actions"][0]["data"]["decision"] == "REJECTED"
    assert body["approvalId"] == run.approval_id
    assert credentials[1] not in json.dumps(body)
    assert credentials[0] not in json.dumps(body)
    assert all("reviewer" not in action.get("data", {}) for action in card["actions"])


@pytest.mark.parametrize(
    "change",
    [
        lambda url: url.replace("https:", "http:"),
        lambda url: url.replace(config().workflow_host, "attacker.example"),
        lambda url: url.replace("/trigger", ":444/trigger"),
        lambda url: url + "#fragment",
        lambda url: url.replace("https://", "https://user@"),
    ],
)
def test_workflow_url_rejects_untrusted_destination(credentials, monkeypatch, change):
    monkeypatch.setenv("ASF_TEAMS_WORKFLOW_URL", change(credentials[0]))
    with pytest.raises(ValueError) as caught:
        managed(credentials)
    assert credentials[1] not in repr(caught.value)
    assert credentials[0] not in repr(caught.value)


def test_callback_secret_must_be_strong(credentials, monkeypatch):
    monkeypatch.setenv("ASF_TEAMS_CALLBACK_SECRET", "fake")
    with pytest.raises(ValueError, match="32"):
        managed(credentials)


@pytest.mark.parametrize("status", [301, 302, 307, 400, 401, 403, 429, 500])
def test_delivery_errors_are_not_retried_or_followed(credentials, status):
    transport = FakeTransport(status=status)
    flow, run, repo = managed(credentials, transport=transport)
    with pytest.raises(TeamsDeliveryError):
        flow.send_approval(run.id)
    assert len(transport.calls) == 1
    assert flow._sent == set()
    assert repo.list_decisions(run.approval_id) == []


@pytest.mark.parametrize("error_type", [URLError, TimeoutError, ValueError, _ResponseTooLargeError])
def test_transport_errors_redact_message_repr_and_logs(credentials, caplog, error_type):
    transport = FakeTransport(error=error_type(credentials[1]))
    flow, run, repo = managed(credentials, transport=transport)
    with caplog.at_level(logging.ERROR), pytest.raises(TeamsDeliveryError) as caught:
        flow.send_approval(run.id)
    assert credentials[1] not in str(caught.value)
    assert credentials[1] not in repr(caught.value)
    assert credentials[0] not in str(caught.value)
    assert credentials[1] not in caplog.text
    assert repo.list_decisions(run.approval_id) == []


@pytest.mark.parametrize("secret", ["", "wrong"])
def test_callback_rejects_missing_or_wrong_auth_without_decision(credentials, secret):
    flow, run, repo = managed(credentials)
    response = asyncio.run(post(create_app(flow, run.id), payload(run), secret))
    assert response.status_code == 401
    assert repo.list_decisions(run.approval_id) == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenantId", "00000000-0000-0000-0000-000000000099"),
        ("teamId", "00000000-0000-0000-0000-000000000099"),
        ("channelId", "other"),
        ("objectId", "00000000-0000-0000-0000-000000000099"),
    ],
)
def test_callback_rejects_wrong_actor_binding(credentials, field, value):
    flow, run, repo = managed(credentials)
    data = payload(run)
    data["actor"][field] = value
    response = asyncio.run(post(create_app(flow, run.id), data, credentials[1]))
    assert response.status_code == 403
    assert repo.list_decisions(run.approval_id) == []


def test_callback_cannot_decide_another_managed_run(credentials):
    flow, run, repo = managed(credentials)
    data = payload(run)
    data["action"]["runId"] = "other"
    response = asyncio.run(post(create_app(flow, run.id), data, credentials[1]))
    assert response.status_code == 403
    assert repo.list_decisions(run.approval_id) == []


@pytest.mark.parametrize("decision", ["REJECTED", "REQUEST_CHANGES"])
def test_callback_requires_negative_feedback(credentials, decision):
    flow, run, repo = managed(credentials)
    response = asyncio.run(
        post(
            create_app(flow, run.id),
            payload(run, decision=decision, comment=" "),
            credentials[1],
        )
    )
    assert response.status_code == 422
    assert repo.list_decisions(run.approval_id) == []


def test_callback_rejects_echoed_secret_without_logging_or_returning_it(credentials, caplog):
    flow, run, repo = managed(credentials)
    data = payload(run)
    data["action"]["reviewer"] = credentials[1]
    response = asyncio.run(post(create_app(flow, run.id), data, credentials[1]))
    assert response.status_code == 422
    assert credentials[1] not in response.text
    assert credentials[1] not in caplog.text
    assert repo.list_decisions(run.approval_id) == []


def test_callback_never_persists_configured_secret_in_feedback(credentials, caplog):
    flow, run, repo = managed(credentials)
    response = asyncio.run(
        post(
            create_app(flow, run.id),
            payload(run, decision="REJECTED", comment=credentials[1]),
            credentials[1],
        )
    )
    assert response.status_code == 422
    assert credentials[1] not in response.text
    assert credentials[1] not in caplog.text
    assert repo.list_decisions(run.approval_id) == []


def test_workflow_does_not_send_configured_secret_in_artifact(credentials):
    flow, run, _ = managed(credentials)
    request = flow.approvals.pending(run.id)
    stored = flow.approvals.engine._runs[run.id]
    original = stored.artifact_history[request.artifact_id]
    stored.artifact_history[request.artifact_id] = original.model_copy(
        update={"content": {"text": credentials[1]}},
    )
    with pytest.raises(TeamsDeliveryError) as caught:
        flow.send_approval(run.id)
    assert credentials[1] not in str(caught.value)
    assert flow._transport.calls == []


@pytest.mark.parametrize("raw,status", [(b"bad json", 422), (b"x" * 16_385, 413)])
def test_callback_bounds_and_malformed_json(credentials, raw, status):
    flow, run, repo = managed(credentials)
    response = asyncio.run(post(create_app(flow, run.id), None, credentials[1], raw=raw))
    assert response.status_code == status
    assert repo.list_decisions(run.approval_id) == []


def test_callback_approve_and_replay(credentials):
    flow, run, repo = managed(credentials)
    app = create_app(flow, run.id)
    first = asyncio.run(post(app, payload(run), credentials[1]))
    second = asyncio.run(post(app, payload(run), credentials[1]))
    assert first.status_code == 200
    assert first.json()["stage"] == "PLAN"
    assert second.status_code == 409
    assert len(repo.list_decisions(run.approval_id)) == 1


def test_callback_expired_approval(credentials):
    flow, run, repo = managed(credentials)
    request = repo.get(run.approval_id)
    repo.update(
        request.model_copy(
            update={
                "expires_at": request.requested_at + timedelta(seconds=1),
            }
        )
    )
    flow.approvals.engine._clock = lambda: request.requested_at + timedelta(seconds=2)
    response = asyncio.run(post(create_app(flow, run.id), payload(run), credentials[1]))
    assert response.status_code == 410
    assert repo.list_decisions(run.approval_id) == []


def test_large_spec_fails_without_sending_partial_text(credentials):
    flow, run, repo = managed(credentials)
    request = flow.approvals.pending(run.id)
    stored = flow.approvals.engine._runs[run.id]
    original = stored.artifact_history[request.artifact_id]
    stored.artifact_history[request.artifact_id] = original.model_copy(
        update={"content": {"text": "x" * 30_000}},
    )
    with pytest.raises(TeamsDeliveryError, match="no partial"):
        flow.send_approval(run.id)
    assert flow._transport.calls == []
    assert repo.list_decisions(run.approval_id) == []


def test_partial_quorum_requests_fresh_card_but_not_for_duplicate_vote(credentials):
    engine, _, _, _ = make_engine(approval=True)
    engine._approval_policy = ApprovalPolicy(reviewers=["reviewer", "second"], min_approvals=2)
    run = engine.tick(start(engine).id)
    flow = TeamsWorkflow(config(), engine, transport=FakeTransport())
    flow.send_approval(run.id)
    data = payload(run)
    assert flow.decide(WorkflowDecision.model_validate(data)).approval_id == run.approval_id
    assert run.approval_id not in flow._sent
    flow.advance(run.id)
    assert len(flow._transport.calls) == 2
    with pytest.raises(ApprovalError):
        flow.decide(WorkflowDecision.model_validate(data))
    assert run.approval_id in flow._sent
    data["actor"]["objectId"] = "00000000-0000-0000-0000-000000000005"
    assert flow.decide(WorkflowDecision.model_validate(data)).state.stage == "PLAN"


def test_waiting_run_does_not_send_duplicate_cards_on_each_poll(credentials):
    flow, run, repo = managed(credentials)
    flow.advance(run.id)
    flow.advance(run.id)
    assert len(flow._transport.calls) == 1
    assert repo.list_decisions(run.approval_id) == []


def test_existing_revision_limit_escalates_without_more_agent_calls(credentials):
    flow, run, _ = managed(credentials)
    for _ in range(3):
        run = flow.approvals.engine.get(run.id)
        flow.decide(
            WorkflowDecision.model_validate(
                payload(run, decision="REJECTED", comment="Fix"),
            )
        )
        run = flow.advance(run.id)
    assert run.state.stage == "SPEC_ESCALATED"
    count = len(run.results)
    assert flow.advance(run.id).state.stage == "SPEC_ESCALATED"
    assert len(flow.approvals.engine.get(run.id).results) == count


def test_authenticated_reject_rewrites_spec_then_approve_automatically_runs_plan(
    credentials,
    tmp_path,
):
    async def scenario():
        store = InMemoryStore()
        try:
            models = DemoModels()
            engine = demo_engine(config(), store, models=models)
            run = engine.start(
                task_id="demo",
                project_id="demo",
                inputs={"spec": {"requirement": "Demo"}},
            )
            transport = FakeTransport()
            flow = TeamsWorkflow(config(), engine, transport=transport)
            app = create_app(flow, run.id, poll_seconds=0.005)

            async def wait_for(predicate):
                deadline = time.monotonic() + 3
                while not predicate():
                    if time.monotonic() >= deadline:
                        pytest.fail("Automatic workflow did not reach expected state")
                    await asyncio.sleep(0.005)

            async with app.router.lifespan_context(app):
                await wait_for(lambda: len(transport.calls) == 1)
                first = engine.get(run.id)
                response = await post(
                    app,
                    payload(first, decision="REJECTED", comment="Add retention policy"),
                    credentials[1],
                )
                assert response.status_code == 200
                assert response.json()["stage"] == "SPEC_DRAFT"
                await wait_for(lambda: len(transport.calls) == 2)
                revised = engine.get(run.id)
                assert revised.state.stage == "SPEC_REVIEW"
                assert revised.artifacts["SPEC"].version == "2"
                assert revised.approval_id != first.approval_id
                assert "Add retention policy" in models.requests[1].messages[-1].content
                assert "Initial demo specification" in models.requests[1].messages[-1].content
                assert (await post(app, payload(first), credentials[1])).status_code == 409
                assert engine.get(run.id).approval_id == revised.approval_id
                assert (await post(app, payload(revised), credentials[1])).status_code == 200
                await wait_for(lambda: engine.get(run.id).state.stage == "COMPLETED")
                completed = engine.get(run.id)
                assert completed.artifacts["PLAN"].metadata["specVersion"] == "2"
                assert completed.artifacts["PLAN"].metadata["specArtifactId"] == (
                    completed.artifacts["SPEC"].id
                )
                assert len(completed.results) == 3
                assert len(transport.calls) == 2
        finally:
            store.close()

    asyncio.run(scenario())


def test_driver_pauses_safely_on_delivery_failure(credentials, caplog):
    flow, run, repo = managed(
        credentials,
        transport=FakeTransport(error=URLError(credentials[1])),
    )

    async def scenario():
        app = create_app(flow, run.id, poll_seconds=0.005)
        async with app.router.lifespan_context(app):
            await asyncio.sleep(0.01)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://local",
            ) as client:
                assert (await client.get("/health")).status_code == 503
            assert (await post(app, payload(run), credentials[1])).status_code == 503

    asyncio.run(scenario())
    assert flow.failure_code == "INTEGRATION_UNAVAILABLE"
    assert credentials[1] not in caplog.text
    assert repo.list_decisions(run.approval_id) == []
