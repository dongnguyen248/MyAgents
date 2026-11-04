"""Demo assembly helpers: persistence of dashboard-created projects."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from asf.api.demo import _project_remover, _project_writer
from asf.configuration.loader import load_project, load_projects
from asf.configuration.project import ProjectProfile


def make_profile(**overrides: Any) -> ProjectProfile:
    data: dict[str, Any] = {
        "id": "demo-x", "name": "Demo X",
        "repository": {"provider": "gitlab"},
        "technology": {"backend": ["python"]},
        "workflow": "software-development",
    }
    data.update(overrides)
    return ProjectProfile(**data)


def test_project_writer_round_trips_through_loader(tmp_path: Path):
    write = _project_writer(tmp_path)
    write(make_profile())
    assert (tmp_path / "demo-x.yaml").is_file()
    loaded = load_projects(tmp_path)
    assert loaded["demo-x"].name == "Demo X"
    assert load_project(tmp_path / "demo-x.yaml").technology == {
        "backend": ["python"],
    }


def test_project_writer_refuses_overwrite_and_literal_secrets(tmp_path: Path):
    write = _project_writer(tmp_path)
    write(make_profile())
    with pytest.raises(ValueError):
        write(make_profile())
    with pytest.raises(ValueError):
        write(make_profile(
            id="demo-y",
            repository={"provider": "gitlab", "token": "literal-secret-value"},
        ))
    assert not (tmp_path / "demo-y.yaml").exists()


def test_project_writer_overwrite_and_remover(tmp_path: Path):
    create = _project_writer(tmp_path)
    update = _project_writer(tmp_path, overwrite=True)
    create(make_profile())
    update(make_profile(name="Demo X2"))
    assert load_project(tmp_path / "demo-x.yaml").name == "Demo X2"
    _project_remover(tmp_path)("demo-x")
    assert not (tmp_path / "demo-x.yaml").exists()
    _project_remover(tmp_path)("demo-x")  # a missing file is tolerated


# ---------------------------------------------------------------------------
# Per-project review rules (configuration.review -> run context)
# ---------------------------------------------------------------------------

from asf.api.demo import DemoFactoryService, build_demo  # noqa: E402


def make_service(tmp_path: Path, configuration: dict[str, Any]) -> DemoFactoryService:
    return DemoFactoryService(
        object(),
        projects={"p": {"id": "p", "name": "P", "configuration": configuration}},
        projects_dir=tmp_path,
    )


def test_review_rules_concatenate_files_then_inline(tmp_path: Path):
    (tmp_path / "a.md").write_text("# A\nrule a", encoding="utf-8")
    (tmp_path / "b.md").write_text("# B\nrule b", encoding="utf-8")
    service = make_service(tmp_path, {"review": {
        "rulesFiles": ["a.md", "b.md"], "rules": "inline rule",
    }})
    text = service._review_rules("p")
    assert text.index("rule a") < text.index("rule b") < text.index("inline rule")


def test_review_rules_absent_configuration_is_empty(tmp_path: Path):
    assert make_service(tmp_path, {})._review_rules("p") == ""
    assert make_service(tmp_path, {"review": {}})._review_rules("p") == ""
    assert make_service(tmp_path, {})._review_rules("unknown") == ""


def test_review_rules_missing_file_fails_loudly(tmp_path: Path):
    service = make_service(tmp_path, {"review": {"rulesFiles": ["nope.md"]}})
    with pytest.raises(ValueError, match="cannot be read"):
        service._review_rules("p")


def test_review_rules_file_cannot_escape_projects_dir(tmp_path: Path):
    service = make_service(tmp_path, {"review": {"rulesFiles": ["../secret.md"]}})
    with pytest.raises(ValueError, match="escapes the projects directory"):
        service._review_rules("p")


def test_vhpc_rules_reach_the_run_context(tmp_path: Path):
    service, _engine, _store = build_demo(tmp_path / "demo.sqlite")
    rules = service._review_rules("vhpc")
    for marker in (
        "Java Coding Rules", "API Design Rules", "Security Rules",
        "TypeScript and React Coding Rules", "Constants and Magic Values",
    ):
        assert marker in rules
    assert service._review_rules("vnpc") == ""
    run = service.start_run(
        "rules-task", "vhpc",
        inputs={"spec": {"requirement": "Check the review rules wiring"}},
    )
    assert "Constants and Magic Values" in run.context["project"]["reviewRules"]
