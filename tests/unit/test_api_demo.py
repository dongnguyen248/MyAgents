"""Demo assembly helpers: persistence of dashboard-created projects."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from asf.api.demo import (
    _project_remover,
    _project_writer,
    _resolve_db_path,
    build_demo,
)
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


# ---------------------------------------------------------------------------
# Per-project review rules (configuration.review -> run context)
# ---------------------------------------------------------------------------

from asf.api.demo import DemoFactoryService  # noqa: E402


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
    # Language packs (java, then typescript) precede the project rules.
    assert rules.index("Java Coding Rules") < rules.index(
        "TypeScript and React Coding Rules",
    ) < rules.index("API Design Rules")
    assert service._review_rules("vnpc") == ""
    run = service.start_run(
        "rules-task", "vhpc",
        inputs={"spec": {"requirement": "Check the review rules wiring"}},
    )
    assert "Constants and Magic Values" in run.context["project"]["reviewRules"]


def write_pack(tmp_path: Path, pack: str, text: str) -> None:
    directory = tmp_path / "rules" / "languages"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{pack}.md").write_text(text, encoding="utf-8")


def make_stack_service(
    tmp_path: Path,
    technology: dict[str, Any],
    configuration: dict[str, Any] | None = None,
) -> DemoFactoryService:
    return DemoFactoryService(
        object(),
        projects={"p": {
            "id": "p", "name": "P", "technology": technology,
            "configuration": configuration or {},
        }},
        projects_dir=tmp_path,
    )


@pytest.mark.parametrize("token", ["csharp", "C#", "dotnet", ".NET"])
def test_csharp_tokens_select_the_csharp_pack(tmp_path: Path, token: str):
    write_pack(tmp_path, "csharp", "# CSharp Pack")
    service = make_stack_service(tmp_path, {"backend": [token]})
    assert service._review_rules("p") == "# CSharp Pack"


def test_react_and_typescript_select_the_typescript_pack_once(tmp_path: Path):
    write_pack(tmp_path, "typescript", "# TS Pack")
    service = make_stack_service(
        tmp_path, {"frontend": ["react", "typescript"]},
    )
    assert service._review_rules("p") == "# TS Pack"


def test_unknown_language_and_missing_pack_add_nothing(tmp_path: Path):
    service = make_stack_service(tmp_path, {"backend": ["python"]})
    assert service._review_rules("p") == ""
    # A mapped language whose pack file is absent is skipped, not fatal.
    service = make_stack_service(tmp_path, {"backend": ["java"]})
    assert service._review_rules("p") == ""


def test_language_packs_precede_project_rules(tmp_path: Path):
    write_pack(tmp_path, "java", "# Java Pack")
    service = make_stack_service(
        tmp_path, {"backend": ["java"]}, {"review": {"rules": "project rule"}},
    )
    text = service._review_rules("p")
    assert text.index("# Java Pack") < text.index("project rule")


def test_retry_run_replays_the_original_inputs(tmp_path: Path):
    service, engine, _store = build_demo(tmp_path / "demo.sqlite")
    run = service.start_run(
        "retry-task", "vhpc",
        inputs={"spec": {"requirement": "Retry me"}},
        context={"title": "Retry demo", "priority": "HIGH"},
    )
    engine.cancel(run.id)
    view = service.retry_run(run.id)
    assert view is not None
    assert view["taskId"] == "retry-task" and view["id"] != run.id
    retried = engine.get(view["id"])
    assert retried.inputs["spec"]["requirement"] == "Retry me"
    assert retried.context["title"] == "Retry demo"
    assert retried.context["priority"] == "HIGH"


def test_retry_run_rejects_a_run_that_is_still_active(tmp_path: Path):
    service, _engine, _store = build_demo(tmp_path / "demo.sqlite")
    run = service.start_run(
        "active-task", "vhpc", inputs={"spec": {"requirement": "Still running"}},
    )
    with pytest.raises(ValueError, match="still active"):
        service.retry_run(run.id)


def test_resolve_db_path_serving_defaults_to_repo_data_dir():
    path = _resolve_db_path(None, selftest=False)
    assert path.name == "asf.sqlite" and path.parent.name == "data"


def test_resolve_db_path_explicit_argument_wins(tmp_path: Path):
    explicit = tmp_path / "custom.sqlite"
    assert _resolve_db_path(explicit, selftest=False) == explicit
    assert _resolve_db_path(explicit, selftest=True) == explicit


def test_resolve_db_path_selftest_keeps_a_temp_db():
    path = _resolve_db_path(None, selftest=True)
    assert path.name == "demo.sqlite" and "asf-api-demo-" in path.parent.name


def test_load_dotenv_reads_pairs_and_keeps_real_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    from asf.api.demo import _load_dotenv

    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "# a comment\n"
        "\n"
        "ASF_MARIADB_PASSWORD=from-file\n"
        'ASF_MARIADB_HOST="db.internal"\n'
        "NOT_A_PAIR\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("ASF_MARIADB_PASSWORD", raising=False)
    monkeypatch.setenv("ASF_MARIADB_HOST", "real-env-wins")
    assert _load_dotenv(dotenv) is True
    assert os.environ["ASF_MARIADB_PASSWORD"] == "from-file"
    assert os.environ["ASF_MARIADB_HOST"] == "real-env-wins"


def test_load_dotenv_missing_file_is_a_no_op(tmp_path: Path):
    from asf.api.demo import _load_dotenv

    assert _load_dotenv(tmp_path / ".env") is False
