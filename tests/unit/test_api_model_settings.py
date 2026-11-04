"""Model settings endpoints over HTTP (demo assembly)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from asf.api.app import create_app
from asf.api.demo import build_demo


def _client(tmp_path: Path) -> TestClient:
    service, _engine, _store = build_demo(tmp_path / "demo.sqlite")
    return TestClient(create_app(service))


def test_settings_round_trip_never_exposes_the_key(tmp_path: Path):
    client = _client(tmp_path)
    initial = client.get("/settings/model")
    assert initial.status_code == 200
    assert initial.json()["provider"] == "scripted"

    updated = client.put("/settings/model", json={
        "provider": "gemini", "model": "gemini-x", "apiKey": "AIza-topsecret",
    })
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
