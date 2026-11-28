from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from asf.agents._shared.rules import RulesFilterOptions, rules_section
from asf.api.agent_rule_settings import AgentRuleSettings, rule_router
from asf.api.rule_catalogue import MAX_RULE_BYTES, resolve_agent_rules


class FakeService:
    def __init__(self, projects: Path, data: Path) -> None:
        self._projects_dir = projects
        self._agent_rule_settings = AgentRuleSettings(data)

    def get_agent(self, agent_id: str):
        if agent_id == "agent-implement":
            return {"type": "implement"}
        if agent_id == "agent-test":
            return {"type": "test"}
        return None


def setup_client(tmp_path: Path) -> tuple[TestClient, FakeService, Path]:
    rules = tmp_path / "rules"
    (rules / "languages").mkdir(parents=True)
    (rules / "languages" / "java.md").write_text("# Java\n\n## API\nJAVA RULE", encoding="utf-8")
    (rules / "common.md").write_text("# Common\n\n## Security\nBASE RULE", encoding="utf-8")
    service = FakeService(tmp_path / "projects", tmp_path / "data" / "agent-rules.json")
    app = FastAPI()
    app.include_router(rule_router(service))
    return TestClient(app), service, rules


def test_catalogue_assignment_edit_and_persistence(tmp_path: Path) -> None:
    client, service, root = setup_client(tmp_path)
    assert [entry["id"] for entry in client.get("/rules").json()] == [
        "common.md",
        "languages/java.md",
    ]
    url = "/agents/agent-implement/rules"
    assert client.get(url).json() == {"rules": []}
    assert client.put(url, json={"rules": ["missing.md"]}).status_code == 422
    assert client.put(url, json={"rules": ["languages/java.md"]}).json() == {
        "rules": ["languages/java.md"]
    }
    assert AgentRuleSettings(tmp_path / "data" / "agent-rules.json").selected("implement") == [
        "languages/java.md"
    ]
    assert client.get("/agents/agent-test/rules").status_code == 400
    assert client.get("/agents/missing/rules").status_code == 404
    file_url = "/rules/files/languages/java.md"
    assert "JAVA RULE" in client.get(file_url).json()["content"]
    assert client.put(file_url, json={"content": "new rule"}).status_code == 200
    assert (root / "languages" / "java.md").read_text(encoding="utf-8") == "new rule"
    assert service._agent_rule_settings.selected("implement") == ["languages/java.md"]
    assert client.put(url, json={"rules": []}).json() == {"rules": []}


def test_rule_paths_are_confined_and_limit_file_size(tmp_path: Path) -> None:
    client, _service, root = setup_client(tmp_path)
    secret = tmp_path / "secret.md"
    secret.write_text("secret", encoding="utf-8")
    (root / "link.md").symlink_to(secret)
    (root / "outside").symlink_to(tmp_path, target_is_directory=True)
    (root / "binary.md").write_bytes(b"\xff")
    response = client.put("/agents/agent-implement/rules", json={"rules": ["binary.md"]})
    assert response.status_code == 422
    assert "link.md" not in [entry["id"] for entry in client.get("/rules").json()]
    for path in ("%2e%2e/secret.md", "link.md", "outside/secret.md", "binary.md"):
        assert client.get(f"/rules/files/{path}").status_code in (400, 404)
        assert client.put(f"/rules/files/{path}", json={"content": "bad"}).status_code in (400, 404)
    assert (
        client.put(
            "/rules/files/common.md", json={"content": "x" * (MAX_RULE_BYTES + 1)}
        ).status_code
        == 413
    )
    assert secret.read_text(encoding="utf-8") == "secret"


def test_extra_rules_are_agent_specific_and_keep_project_rules(tmp_path: Path) -> None:
    _client, _service, root = setup_client(tmp_path)
    baseline = (root / "common.md").read_text(encoding="utf-8").strip()
    selected = {"implement": ["common.md", "languages/java.md"]}
    extra = resolve_agent_rules(root, selected, baseline)
    project = {"reviewRules": baseline, "agentRules": extra}
    implement = rules_section(project, "Rules", agent="implement")
    assert implement.count("BASE RULE") == 1
    assert "JAVA RULE" in implement
    assert "JAVA RULE" not in rules_section(project, "Rules", agent="review")
    assert "BASE RULE" in rules_section(project, "Rules", agent="review")
    assert rules_section(project, "Rules", RulesFilterOptions(agent="spec", stack=frozenset()))
    (root / "languages" / "java.md").unlink()
    with pytest.raises(ValueError, match="java.md"):
        resolve_agent_rules(root, selected, baseline)


def test_additional_rules_enter_actual_agent_prompts_and_persist(tmp_path: Path) -> None:
    from asf.agents._shared.design_prompts import DesignSystemOptions, build_design_system_content
    from asf.agents._shared.harness import HarnessComponents
    from asf.agents.implement.prompts import (
        ImplementPromptContext,
        ImplementPrompts,
        build_implement_messages,
    )
    from asf.agents.review.prompts import ReviewPrompts, _system_message
    from asf.api.app import create_app
    from asf.api.demo import build_demo

    projects = tmp_path / "projects"
    rules = tmp_path / "rules"
    rules.mkdir(parents=True)
    projects.mkdir(parents=True)
    (rules / "base.md").write_text("# Base\n\n## Security\nBASE CONTENT", encoding="utf-8")
    (rules / "extra.md").write_text("# Extra\n\n## Security\nEXTRA CONTENT", encoding="utf-8")
    service, _engine, _store = build_demo(tmp_path / "data", ephemeral=True)
    service._projects_dir = projects
    service._projects["p"] = {"technologies": []}
    service._project_profiles["p"] = {
        "enabledSkills": [],
        "configuration": {"review": {"rulesFiles": ["rules/base.md"]}},
    }
    client = TestClient(create_app(service))
    for agent in ("implement", "spec"):
        assert (
            client.put(f"/agents/agent-{agent}/rules", json={"rules": ["extra.md"]}).status_code
            == 200
        )
    project = service._build_initial_context("p", {})["project"]
    context = ImplementPromptContext(
        prompts=ImplementPrompts(system="system"),
        spec_artifact={},
        plan_artifact={},
        task_artifact={},
        task_item_id="T1",
        existing_files={},
        language=None,
        project_context=project,
    )
    implement = build_implement_messages(context)[0].content
    review = _system_message(ReviewPrompts(system="system"), project)
    spec = build_design_system_content(
        HarnessComponents(system="system"),
        project,
        DesignSystemOptions(agent_type="spec", rules_intro="Rules", task_stack=frozenset()),
    )
    assert "BASE CONTENT" in implement and "EXTRA CONTENT" in implement
    assert "BASE CONTENT" in review and "EXTRA CONTENT" not in review
    assert "BASE CONTENT" in spec and "EXTRA CONTENT" in spec
    service._agent_rule_settings.save("implement", [])
    assert "EXTRA CONTENT" in build_implement_messages(context)[0].content
    restored, _engine, _store = build_demo(tmp_path / "data", ephemeral=True)
    assert restored._agent_rule_settings.selected("spec") == ["extra.md"]
    assert restored._agent_rule_settings.selected("implement") == []
