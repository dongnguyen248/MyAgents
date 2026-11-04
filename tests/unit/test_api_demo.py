"""Demo assembly helpers: persistence of dashboard-created projects."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from asf.api.demo import _project_writer
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
