"""Model settings endpoints over HTTP (demo assembly)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from asf.api.app import create_app
from asf.api.demo import build_demo


def _client(tmp_path: Path) -> TestClient:
    service, _engine, _store = build_demo(tmp_path, ephemeral=True)
    return TestClient(create_app(service))


def test_settings_round_trip_never_exposes_the_key(tmp_path: Path):
    client = _client(tmp_path)
    initial = client.get("/settings/model")
    assert initial.status_code == 200
    assert initial.json()["provider"] == "scripted"

    updated = client.put(
        "/settings/model",
        json={
            "provider": "gemini",
            "model": "gemini-x",
            "apiKey": "AIza-topsecret",
        },
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["keyConfigured"] is True
    assert body["keyHint"] == "…cret"
    assert "topsecret" not in updated.text

    fetched = client.get("/settings/model")
    assert fetched.json()["model"] == "gemini-x"
    assert "topsecret" not in fetched.text

    # The settings file landed beside the run DB.
    assert (tmp_path / "model-settings.json").is_file()


def test_settings_validation_and_connection_test(tmp_path: Path):
    client = _client(tmp_path)
    bad = client.put("/settings/model", json={"provider": "nope"})
    assert bad.status_code == 422

    scripted = client.post("/settings/model/test")
    assert scripted.status_code == 200
    assert scripted.json()["ok"] is True

    client.put("/settings/model", json={"provider": "openai", "model": "gpt-x"})
    missing_key = client.post("/settings/model/test")
    assert missing_key.json()["ok"] is False
    assert "No API key stored" in missing_key.json()["message"]


def test_settings_per_agent_models_round_trip(tmp_path: Path):
    client = _client(tmp_path)
    # Per-agent connection test on the scripted provider: a known agent
    # answers ok, an unknown one (test never calls a model) does not.
    ok = client.post("/settings/model/test", json={"agent": "implement"})
    assert ok.status_code == 200
    assert ok.json()["ok"] is True
    unknown = client.post("/settings/model/test", json={"agent": "test"})
    assert unknown.json()["ok"] is False

    updated = client.put(
        "/settings/model",
        json={
            "provider": "custom",
            "model": "shared-m",
            "baseUrl": "http://127.0.0.1:4141/v1",
            "apiKey": "placeholder",
            "agentModels": {"implement": "gpt-code", "spec": "claude-spec"},
        },
    )
    assert updated.status_code == 200
    assert updated.json()["agentModels"] == {
        "implement": "gpt-code",
        "spec": "claude-spec",
    }
    fetched = client.get("/settings/model")
    assert fetched.json()["agentModels"]["implement"] == "gpt-code"

    # Unknown agents are rejected; the Test agent has no model.
    bad = client.put(
        "/settings/model",
        json={
            "provider": "custom",
            "model": "shared-m",
            "baseUrl": "http://127.0.0.1:4141/v1",
            "agentModels": {"test": "m"},
        },
    )
    assert bad.status_code == 422


def test_settings_artifact_review_override_round_trip(tmp_path: Path):
    client = _client(tmp_path)
    # The artifact-review agent has its own override slot and its own
    # connection test; the decomposer has neither (it always uses the
    # shared model via the complex tier).
    ok = client.post("/settings/model/test", json={"agent": "artifact-review"})
    assert ok.status_code == 200
    assert ok.json()["ok"] is True

    updated = client.put(
        "/settings/model",
        json={
            "provider": "custom",
            "model": "shared-m",
            "baseUrl": "http://127.0.0.1:4141/v1",
            "apiKey": "placeholder",
            "agentModels": {"artifact-review": "claude-reviewer"},
        },
    )
    assert updated.status_code == 200
    assert updated.json()["agentModels"] == {"artifact-review": "claude-reviewer"}
    fetched = client.get("/settings/model")
    assert fetched.json()["agentModels"]["artifact-review"] == "claude-reviewer"

    bad = client.put(
        "/settings/model",
        json={
            "provider": "custom",
            "model": "shared-m",
            "baseUrl": "http://127.0.0.1:4141/v1",
            "agentModels": {"decomposer": "m"},
        },
    )
    assert bad.status_code == 422
