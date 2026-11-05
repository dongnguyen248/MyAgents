from __future__ import annotations

import argparse
import asyncio

import httpx
import pytest
import yaml

from asf.integrations.teams.demo import DemoModels, demo_engine, main, run_demo
from asf.storage.memory import InMemoryStore
from tests.unit.test_teams_approval import config


def test_offline_demo_engine_revises_then_approves_and_runs_plan(tmp_path):
    store = InMemoryStore()
    models = DemoModels()
    engine = demo_engine(config(), store, models=models)
    run = engine.start(
        task_id="demo",
        project_id="demo",
        inputs={"spec": {"requirement": "Demo approval"}},
    )
    run = engine.tick(run.id)
    assert run.state.stage == "SPEC_REVIEW"
    first = run.approval_id
    run = engine.decide(
        run.id,
        reviewer="reviewer",
        decision="REJECTED",
        comment="Add a retention policy",
        expected_approval_id=first,
    )
    assert run.state.stage == "SPEC_DRAFT"
    run = engine.tick(run.id)
    assert run.state.stage == "SPEC_REVIEW"
    assert run.approval_id != first
    assert run.artifacts["SPEC"].version == "2"
    assert "Add a retention policy" in models.requests[1].messages[-1].content
    assert "Initial demo specification" in models.requests[1].messages[-1].content
    assert "Revised demo specification" in run.artifacts["SPEC"].content["text"]
    run = engine.decide(
        run.id,
        reviewer="reviewer",
        decision="APPROVED",
        expected_approval_id=run.approval_id,
    )
    assert run.state.stage == "PLAN"
    run = engine.tick(run.id)
    assert run.state.stage == "COMPLETED"
    assert run.artifacts["PLAN"].metadata["specArtifactId"] == run.artifacts["SPEC"].id
    assert run.artifacts["PLAN"].metadata["specVersion"] == "2"
    reopened = demo_engine(config(), store)
    assert reopened.get(run.id).state.stage == "COMPLETED"
    store.close()


@pytest.mark.parametrize("gemini", [False, True])
def test_manual_demo_wiring_without_real_network(tmp_path, monkeypatch, capsys, gemini):
    # run_demo picks MariaDB when ASF_MARIADB_PASSWORD is present in
    # the environment; other tests in this process may have loaded a
    # .env (the dotenv loader uses setdefault), so pin the in-memory
    # path explicitly.
    monkeypatch.delenv("ASF_MARIADB_PASSWORD", raising=False)
    settings = config()
    (tmp_path / "platform.yaml").write_text(
        yaml.safe_dump(
            {
                "notifications": [
                    {
                        "name": "teams-approvals",
                        "type": "teams-workflow",
                        "credentials": {"env": settings.credentials.env},
                        "settings": settings.model_dump(
                            mode="json", by_alias=True, exclude={"credentials"}
                        ),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ASF_TEAMS_WORKFLOW_URL", f"https://{settings.workflow_host}/trigger")
    monkeypatch.setenv("ASF_TEAMS_CALLBACK_SECRET", "fake-" + "x" * 32)
    calls = []
    model_calls = []

    def fake_gateway(**kwargs):
        model_calls.append(kwargs)
        return DemoModels()

    monkeypatch.setattr(
        "asf.integrations.teams.demo.GeminiModelGateway.from_environment",
        fake_gateway,
    )
    monkeypatch.setenv("ASF_LIVE_GEMINI_MODEL", "fake-model")

    def serve(app, *, host, port, access_log):
        calls.append((host, port, access_log))

        async def check():
            async with app.router.lifespan_context(app):
                await asyncio.sleep(0)
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="http://local",
                ) as client:
                    assert (await client.get("/health")).status_code == 503

        asyncio.run(check())

    from asf.integrations.teams.workflow import TeamsDeliveryError

    def fail_before_network(self, run_id):
        raise TeamsDeliveryError("Simulated delivery failure")

    monkeypatch.setattr(
        "asf.integrations.teams.workflow.TeamsWorkflow.send_approval",
        fail_before_network,
    )
    monkeypatch.setattr("uvicorn.run", serve)
    run_demo(
        argparse.Namespace(
            config_dir=tmp_path,
            channel="teams-approvals",
            run_id=None,
            port=3978,
            gemini=gemini,
            requirement="Demo",
        )
    )
    assert calls == [("127.0.0.1", 3978, False)]
    assert "Demo run:" in capsys.readouterr().out
    assert len(model_calls) == int(gemini)
    if gemini:
        assert model_calls[0]["model"] == "fake-model"
        assert model_calls[0]["evidence"].last_path is None


def test_demo_requires_explicit_send_acknowledgment(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["teams-demo"])
    with pytest.raises(SystemExit) as caught:
        main()
    assert caught.value.code == 2
    assert "--send is required" in capsys.readouterr().err


def test_live_demo_cannot_resume_and_reset_request_budget():
    with pytest.raises(ValueError, match="cannot resume"):
        run_demo(argparse.Namespace(gemini=True, run_id="existing"))


def test_demo_execution_id_matches_correlation_id(tmp_path):
    store = InMemoryStore()
    try:
        engine = demo_engine(config(), store, execution_id="correlation")
        run = engine.start(
            task_id="demo",
            project_id="demo",
            inputs={"spec": {"requirement": "Demo"}},
        )
        assert run.id == "correlation"
        assert engine.tick(run.id).state.stage == "SPEC_REVIEW"
    finally:
        store.close()
