"""Demo assembly helpers: persistence of dashboard-created projects."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from asf.api.demo import _project_remover, _project_writer, build_demo
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


def test_demo_engine_has_bounded_code_loop_enabled(tmp_path: Path):
    _service, engine, _store = build_demo(tmp_path / "demo.sqlite")
    assert engine._code_loop is not None
    assert engine._code_loop.max_fixes == 3


def test_workflow_view_exposes_artifact_contents(tmp_path: Path):
    service, engine, _store = build_demo(tmp_path / "demo.sqlite")
    run = service.start_run(
        "artifact-task", service.list_projects()[0]["id"],
        inputs={
            "spec": {"requirement": "Demonstrate the artifacts view"},
            "implement": {"taskItemId": "T1", "ref": "main"},
            "review": {"taskItemId": "T1", "ref": "main"},
            "test": {"taskItemId": "T1", "ref": "main"},
        },
    )
    for _ in range(40):
        if run.state.stage in ("COMPLETED", "FAILED", "CANCELLED"):
            break
        if run.approval_id:
            run = engine.decide(run.id, reviewer="dashboard", decision="APPROVED")
        else:
            run = engine.tick(run.id)
    assert run.state.stage == "COMPLETED"
    view = service.get_workflow(run.id)
    assert view is not None
    artifacts = {entry["type"]: entry for entry in view["artifacts"]}
    assert "TEST_REPORT" in artifacts
    content = artifacts["TEST_REPORT"]["content"]
    assert isinstance(content, str) and "PASS" in content
