from pathlib import Path

from fastapi.testclient import TestClient

from asf.api.app import create_app
from asf.api.demo import DemoFactoryService, _project_writer
from asf.configuration.loader import load_project


def setup_project(tmp_path: Path):
    projects = tmp_path / "projects"
    rules = tmp_path / "rules"
    projects.mkdir()
    (rules / "languages").mkdir(parents=True)
    (rules / "languages" / "java.md").write_text("JAVA PACK", encoding="utf-8")
    (rules / "team.md").write_text("TEAM RULE", encoding="utf-8")
    (rules / "agent.md").write_text("AGENT RULE", encoding="utf-8")
    (projects / "old.md").write_text("LEGACY RULE", encoding="utf-8")
    service = DemoFactoryService(
        object(),
        projects={},
        projects_dir=projects,
        on_project_created=_project_writer(projects),
        on_project_updated=_project_writer(projects, overwrite=True),
    )
    return TestClient(create_app(service)), service, projects, rules


def payload():
    return {
        "id": "project-a",
        "name": "Project A",
        "repository": {"provider": "gitlab"},
        "technology": {"backend": ["java"]},
        "workflow": "software-development",
        "enabledRules": ["team.md", "languages/java.md"],
        "configuration": {"review": {"rulesFiles": ["old.md"], "rules": "INLINE RULE"}},
    }


def test_project_create_update_persistence_and_runtime_scope(tmp_path: Path):
    client, service, projects, rules = setup_project(tmp_path)
    created = client.post("/projects", json=payload())
    assert created.status_code == 201, created.text
    assert created.json()["enabledRules"] == ["team.md", "languages/java.md"]
    assert created.json()["legacyRuleFiles"] == ["old.md"]
    assert created.json()["hasInlineRules"] is True
    assert load_project(projects / "project-a.yaml").enabled_rules == payload()["enabledRules"]
    service._agent_rule_settings.save("implement", ["team.md", "agent.md"])
    first = service._build_initial_context("project-a", {})["project"]
    assert first["reviewRules"].count("JAVA PACK") == 1
    assert "TEAM RULE" in first["reviewRules"]
    assert "LEGACY RULE" in first["reviewRules"] and "INLINE RULE" in first["reviewRules"]
    assert first["agentRules"] == {"implement": "AGENT RULE"}
    updated = client.put("/projects/project-a", json={"enabledRules": []})
    assert updated.status_code == 200, updated.text
    assert updated.json()["enabledRules"] == []
    loaded = load_project(projects / "project-a.yaml")
    assert loaded.enabled_rules == []
    assert loaded.configuration["review"] == payload()["configuration"]["review"]
    second = service._build_initial_context("project-a", {})["project"]
    assert "TEAM RULE" not in second["reviewRules"]
    assert "TEAM RULE" in second["agentRules"]["implement"]
    (rules / "agent.md").write_text("CHANGED RULE", encoding="utf-8")
    assert first["agentRules"]["implement"] == "AGENT RULE"
    assert (
        "CHANGED RULE"
        in service._build_initial_context("project-a", {})["project"]["agentRules"]["implement"]
    )


def test_project_rejects_missing_invalid_and_unreadable_rules(tmp_path: Path):
    client, _service, _projects, rules = setup_project(tmp_path)
    for invalid in (["missing.md"], ["../team.md"], ["team.md", "team.md"]):
        assert (
            client.post("/projects", json={**payload(), "enabledRules": invalid}).status_code == 422
        )
    (rules / "bad.md").write_bytes(b"\xff")
    assert (
        client.post("/projects", json={**payload(), "enabledRules": ["bad.md"]}).status_code == 422
    )
    assert client.post("/projects", json=payload()).status_code == 201
    assert (
        client.put("/projects/project-a", json={"enabledRules": ["missing.md"]}).status_code == 422
    )
    assert client.get("/projects").json()[0]["enabledRules"] == payload()["enabledRules"]


def test_legacy_shared_rule_path_is_resolved_after_move(tmp_path: Path):
    client, service, _projects, _rules = setup_project(tmp_path)
    profile = {
        **payload(),
        "enabledRules": [],
        "configuration": {"review": {"rulesFiles": ["rules/team.md"]}},
    }
    assert client.post("/projects", json=profile).status_code == 201
    assert "TEAM RULE" in service._build_initial_context("project-a", {})["project"]["reviewRules"]
