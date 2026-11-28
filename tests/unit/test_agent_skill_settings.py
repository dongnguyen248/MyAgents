from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from asf.agents._shared.skills import skills_for_agent
from asf.api.agent_skill_settings import AgentSkillSettings, register_agent_skill_routes


class FakeService:
    def __init__(self, root: Path, data: Path) -> None:
        self._skills_dir = root
        self._agent_skill_settings = AgentSkillSettings(data)

    def get_agent(self, agent_id: str):
        if agent_id == "agent-implement":
            return {"type": "implement"}
        if agent_id == "agent-test":
            return {"type": "test"}
        return None


def client_for(service: FakeService) -> TestClient:
    app = FastAPI()
    register_agent_skill_routes(app, service)
    return TestClient(app)


def test_skill_assignment_persists_and_updates_catalogue(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    directory = root / "custom"
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text("---\nname: custom\ndescription: demo\n---\nBody")
    path = tmp_path / "data" / "agent-skills.json"
    service = FakeService(root, path)
    client = client_for(service)
    assert "general" in client.get("/agents/agent-implement/skills").json()["skills"]
    assert (
        client.put("/agents/agent-implement/skills", json={"skills": ["unknown"]}).status_code
        == 422
    )
    response = client.put("/agents/agent-implement/skills", json={"skills": ["custom"]})
    assert response.status_code == 200
    assert response.json() == {"skills": ["custom"]}
    assert AgentSkillSettings(path).selected("implement") == ["custom"]
    assert client.get("/skills").json()[0]["appliesTo"] == ["implement"]
    assert client.put("/agents/agent-test/skills", json={"skills": []}).status_code == 400
    assert client.get("/agents/missing/skills").status_code == 404
    assert client.put("/agents/agent-implement/skills", json={"skills": []}).json() == {
        "skills": []
    }
    assert AgentSkillSettings(path).selected("implement") == []


def test_skill_overrides_respect_project_content_stack_and_digest() -> None:
    entries = [
        {"id": "custom", "content": "Custom body", "digest": "Custom digest"},
        {"id": "python", "content": "Python body", "digest": "Python digest"},
        {"id": "general", "content": "General body", "digest": "General digest"},
    ]
    project = {
        "skills": entries,
        "agentSkills": {"implement": ["custom", "python"], "plan": ["custom"]},
    }
    assert skills_for_agent(project, "implement", frozenset({"java"})) == [
        ("custom", "Custom body")
    ]
    assert skills_for_agent(project, "plan") == [("custom", "Custom digest")]
    assert skills_for_agent({"skills": entries}, "implement") == [
        ("python", "Python body"),
        ("general", "General body"),
    ]
    assert (
        skills_for_agent({"skills": entries, "agentSkills": {"implement": []}}, "implement") == []
    )
    assert (
        skills_for_agent({"skills": [], "agentSkills": {"implement": ["custom"]}}, "implement")
        == []
    )
