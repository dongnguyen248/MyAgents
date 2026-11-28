from pathlib import Path

from fastapi.testclient import TestClient

from asf.agents._shared.skills import skills_for_agent
from asf.api.app import create_app
from asf.api.demo import build_demo


def test_agent_setup_routes_persist_and_reach_run_context(tmp_path: Path) -> None:
    service, _engine, _store = build_demo(tmp_path, ephemeral=True)
    client = TestClient(create_app(service))
    response = client.put("/agents/agent-spec/skills", json={"skills": ["react"]})
    assert response.status_code == 200
    assert client.get("/agents/agent-spec/config").json()["skills"] == ["react"]
    context = service._build_initial_context("vhpc", {})
    assert [item[0] for item in skills_for_agent(context["project"], "spec")] == ["react"]
    restarted, _engine, _store = build_demo(tmp_path, ephemeral=True)
    assert restarted._agent_skill_settings.selected("spec") == ["react"]


def test_agent_model_settings_use_existing_backend_and_mask_key(tmp_path: Path) -> None:
    service, _engine, _store = build_demo(tmp_path, ephemeral=True)
    client = TestClient(create_app(service))
    response = client.put(
        "/settings/model",
        json={
            "provider": "scripted",
            "agentModels": {"spec": "test-model"},
            "agentConnections": {"spec": {"provider": "openai", "apiKey": "fake-secret-1234"}},
        },
    )
    assert response.status_code == 200, response.text
    assert "fake-secret-1234" not in response.text
    assert response.json()["agentConnections"]["spec"]["keyConfigured"] is True
    assert service._model_settings.effective_model("spec") == "test-model"
    restarted, _engine, _store = build_demo(tmp_path, ephemeral=True)
    assert restarted._model_settings.effective_model("spec") == "test-model"
    assert restarted._model_settings.effective_settings("spec")["provider"] == "openai"
