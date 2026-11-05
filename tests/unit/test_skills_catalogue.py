"""The skills catalogue and the shared skills prompt helper.

The catalogue is data the agents consume at runtime, so it is
validated like code: every SKILL.md must carry standard Agent
Skills frontmatter (name matching its folder, a real description),
a non-placeholder body, and an entry in the applicability map —
and the map must not name skills that do not exist.
"""

from __future__ import annotations

from pathlib import Path

from asf.agents._shared.skills import (
    SKILL_AGENTS,
    agent_skill_ids,
    skills_for_agent,
    skills_section,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / "skills"


def _catalogue() -> dict[str, str]:
    return {
        folder.name: (folder / "SKILL.md").read_text(encoding="utf-8")
        for folder in sorted(SKILLS_DIR.iterdir())
        if folder.is_dir() and (folder / "SKILL.md").is_file()
    }


def _frontmatter(text: str) -> dict[str, str]:
    assert text.startswith("---"), "SKILL.md must open with frontmatter"
    lines = text.splitlines()
    end = lines.index("---", 1)
    fields: dict[str, str] = {}
    for line in lines[1:end]:
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields


def test_catalogue_matches_the_applicability_map():
    catalogue = _catalogue()
    assert set(catalogue) == set(SKILL_AGENTS), (
        "skills/ folders and SKILL_AGENTS must name the same skills"
    )


def test_every_skill_follows_the_agent_skills_format():
    for skill_id, text in _catalogue().items():
        fields = _frontmatter(text)
        assert fields.get("name") == skill_id
        description = fields.get("description", "")
        assert 40 <= len(description) <= 1024, skill_id
        body = text.split("---", 2)[-1]
        assert "placeholder" not in body.lower(), skill_id
        assert len(body.strip()) > 500, f"{skill_id} body is too thin"


def test_agent_skill_ids_reflect_the_map():
    assert agent_skill_ids("spec") == ["general", "security"]
    assert agent_skill_ids("review") == [
        "code-review", "database", "general", "java", "python",
        "react", "security", "software-development", "spring", "testing",
    ]
    assert agent_skill_ids("test") == ["testing"]
    assert agent_skill_ids("unknown-agent") == []


def test_skills_section_filters_by_agent():
    project = {
        "skills": [
            {"id": "general", "content": "GENERAL BODY"},
            {"id": "git", "content": "GIT BODY"},
            {"id": "testing", "content": "TESTING BODY"},
        ],
    }
    spec = skills_section(project, "spec")
    assert "GENERAL BODY" in spec
    assert "GIT BODY" not in spec  # git does not apply to spec
    assert "TESTING BODY" not in spec

    implement = skills_section(project, "implement")
    assert "GENERAL BODY" in implement
    assert "GIT BODY" in implement
    assert "TESTING BODY" in implement

    assert skills_for_agent(project, "plan") == [("general", "GENERAL BODY")]
    assert skills_section({}, "spec") == ""
    assert skills_section({"skills": "nope"}, "spec") == ""


def test_skills_section_accepts_a_json_project_context():
    project = '{"skills": [{"id": "security", "content": "SEC BODY"}]}'
    assert "SEC BODY" in skills_section(project, "review")
    assert skills_section(project, "plan") == ""
    assert skills_section("{broken", "review") == ""
