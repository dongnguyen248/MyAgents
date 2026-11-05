"""Demo assembly helpers: persistence of dashboard-created projects."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

import pytest

from asf.api.demo import (
    _project_remover,
    _project_writer,
    _resolve_data_dir,
    build_demo,
)
from asf.configuration.loader import load_project, load_projects
from asf.configuration.project import ProjectProfile


def make_profile(**overrides: Any) -> ProjectProfile:
    data: dict[str, Any] = {
        "id": "demo-x",
        "name": "Demo X",
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
        write(
            make_profile(
                id="demo-y",
                repository={"provider": "gitlab", "token": "literal-secret-value"},
            )
        )
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
    _service, engine, _store = build_demo(tmp_path, ephemeral=True)
    assert engine._code_loop is not None
    assert engine._code_loop.max_fixes == 3


def test_workflow_view_exposes_artifact_contents(tmp_path: Path):
    service, engine, _store = build_demo(tmp_path, ephemeral=True)
    run = service.start_run(
        "artifact-task",
        service.list_projects()[0]["id"],
        inputs={
            "spec": {"requirement": "Demonstrate the artifacts view"},
            "implement": {"taskItemId": "T1", "ref": "main"},
            "review": {"taskItemId": "T1", "ref": "main"},
            "test": {"taskItemId": "T1", "ref": "main"},
        },
    )
    # start_run also spawns the service's background drive; the manual
    # loop below must be the only driver (the engine refuses a second
    # concurrent dispatcher), so wait for the drive to park first.
    # Without this the two drivers race and the test flakes.
    service.wait_for_drives()
    run = engine.get(run.id)
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

from datetime import UTC  # noqa: E402

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
    service = make_service(
        tmp_path,
        {
            "review": {
                "rulesFiles": ["a.md", "b.md"],
                "rules": "inline rule",
            }
        },
    )
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


def test_project_skills_resolve_from_the_catalogue(tmp_path: Path):
    service, _engine, _store = build_demo(tmp_path, ephemeral=True)
    skills = service._project_skills("vhpc")
    assert [entry["id"] for entry in skills] == [
        "java",
        "spring",
        "react",
        "git",
        "testing",
        "security",
    ]
    by_id = {entry["id"]: entry["content"] for entry in skills}
    # Bodies arrive with frontmatter stripped and real content.
    assert by_id["java"].startswith("# Java craft")
    assert "name: java" not in by_id["java"]
    assert "placeholder" not in by_id["testing"].lower()


def test_project_skills_missing_file_fails_loudly(tmp_path: Path):
    service, _engine, _store = build_demo(tmp_path, ephemeral=True)
    service._project_profiles["broken"] = {"enabledSkills": ["no-such-skill"]}
    with pytest.raises(ValueError, match="no-such-skill"):
        service._project_skills("broken")


def test_run_context_carries_the_projects_enabled_skills(tmp_path: Path):
    service, engine, _store = build_demo(tmp_path, ephemeral=True)
    project_id = service.list_projects()[0]["id"]
    enabled = service._project_profiles[project_id]["enabledSkills"]
    run = service.start_run(
        "skills-task",
        project_id,
        inputs={"spec": {"requirement": "Demonstrate skills in context"}},
    )
    project = engine.get(run.id).context["project"]
    assert project["enabledSkills"] == enabled
    assert [entry["id"] for entry in project["skills"]] == enabled


def test_vhpc_rules_reach_the_run_context(tmp_path: Path):
    service, _engine, _store = build_demo(tmp_path, ephemeral=True)
    rules = service._review_rules("vhpc")
    for marker in (
        "Java Coding Rules",
        "API Design Rules",
        "Security Rules",
        "TypeScript and React Coding Rules",
        "Constants and Magic Values",
    ):
        assert marker in rules
    # Language packs (java, then typescript) precede the project rules.
    assert (
        rules.index("Java Coding Rules")
        < rules.index(
            "TypeScript and React Coding Rules",
        )
        < rules.index("API Design Rules")
    )
    assert service._review_rules("vnpc") == ""
    run = service.start_run(
        "rules-task",
        "vhpc",
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
        projects={
            "p": {
                "id": "p",
                "name": "P",
                "technology": technology,
                "configuration": configuration or {},
            }
        },
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
        tmp_path,
        {"frontend": ["react", "typescript"]},
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
        tmp_path,
        {"backend": ["java"]},
        {"review": {"rules": "project rule"}},
    )
    text = service._review_rules("p")
    assert text.index("# Java Pack") < text.index("project rule")


def test_retry_run_replays_the_original_inputs(tmp_path: Path):
    service, engine, _store = build_demo(tmp_path, ephemeral=True)
    run = service.start_run(
        "retry-task",
        "vhpc",
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
    service, _engine, _store = build_demo(tmp_path, ephemeral=True)
    run = service.start_run(
        "active-task",
        "vhpc",
        inputs={"spec": {"requirement": "Still running"}},
    )
    with pytest.raises(ValueError, match="still active"):
        service.retry_run(run.id)


def test_resolve_data_dir_serving_defaults_to_repo_data_dir():
    path = _resolve_data_dir(selftest=False)
    assert path.name == "data"


def test_resolve_data_dir_selftest_keeps_a_temp_dir():
    path = _resolve_data_dir(selftest=True)
    assert "asf-api-demo-" in path.name


def test_build_demo_without_store_or_ephemeral_requires_mariadb_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # No silent fallback: without ASF_MARIADB_PASSWORD (and without
    # an explicit store or the ephemeral flag) assembly refuses
    # with the configuration guidance.
    monkeypatch.delenv("ASF_MARIADB_PASSWORD", raising=False)
    with pytest.raises(ValueError, match="No execution store is configured"):
        build_demo(tmp_path)


def test_load_dotenv_reads_pairs_and_keeps_real_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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


def test_resume_run_continues_from_the_failed_step(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    service, engine, _store = build_demo(tmp_path, ephemeral=True)
    spec_agent = engine._registry.for_type("spec")

    def explode(request: object) -> object:
        raise RuntimeError("gateway down")

    # The spec agent dies during the start run's automatic advance.
    monkeypatch.setattr(spec_agent, "execute", explode)
    run = service.start_run(
        "resume-task",
        "vhpc",
        inputs={"spec": {"requirement": "Resume me"}},
    )
    service.wait_for_drives()
    assert engine.get(run.id).state.stage == "FAILED"
    monkeypatch.undo()

    # Resume re-runs the spec step and auto-advances to its approval gate.
    view = service.resume_run(run.id)
    service.wait_for_drives()
    view = service.get_workflow(view["id"]) if view is not None else None
    assert view is not None
    assert view["id"] != run.id and view["status"] == "WAITING_APPROVAL"
    resumed = engine.get(view["id"])
    assert resumed.state.stage == "SPEC_REVIEW"
    assert resumed.inputs["spec"]["requirement"] == "Resume me"
    assert engine.get(run.id).state.stage == "FAILED"


def test_resume_run_rejects_a_run_that_has_not_failed(tmp_path: Path):
    service, _engine, _store = build_demo(tmp_path, ephemeral=True)
    run = service.start_run(
        "active-task-2",
        "vhpc",
        inputs={"spec": {"requirement": "Still running"}},
    )
    with pytest.raises(ValueError, match="has not failed"):
        service.resume_run(run.id)


def test_run_advances_on_its_own_between_approvals(tmp_path: Path):
    service, engine, _store = build_demo(tmp_path, ephemeral=True)
    run = service.start_run(
        "hands-free",
        "vhpc",
        inputs={"spec": {"requirement": "No ticking"}},
    )
    # Creation alone already produced the spec and parked at its gate.
    service.wait_for_drives()
    view = service.get_workflow(run.id)
    assert view is not None and view["status"] == "WAITING_APPROVAL"
    # From here the only human input is approvals — never a tick — and
    # each approval carries the run to the next gate on its own.
    for _ in range(5):
        pending = service.list_approvals()
        if not pending:
            break
        service.decide_approval(pending[0]["id"], decision="APPROVE")
        service.wait_for_drives()
    view = service.get_workflow(run.id)
    assert view is not None and view["status"] == "COMPLETED"
    assert engine.get(run.id).state.stage == "COMPLETED"


def test_run_with_all_approvals_skipped_needs_no_approvals(tmp_path: Path):
    # Dong's simple-task case: every gate skipped at creation — the
    # run drives itself to completion and no approval is ever created.
    service, engine, _store = build_demo(tmp_path, ephemeral=True)
    run = service.start_run(
        "hands-free-skip",
        "vhpc",
        inputs={"spec": {"requirement": "Simple task"}},
        context={"skipApprovals": ["spec", "plan", "task"]},
    )
    service.wait_for_drives()
    view = service.get_workflow(run.id)
    assert view is not None and view["status"] == "COMPLETED"
    assert engine.get(run.id).state.stage == "COMPLETED"
    assert service.list_approvals() == []
    states = {step["id"]: step["state"] for step in view["steps"]}
    assert states["spec_approval"] == "skipped"
    assert states["plan_approval"] == "skipped"
    assert states["task_approval"] == "skipped"


def test_workflow_view_exposes_the_failure_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    service, engine, _store = build_demo(tmp_path, ephemeral=True)
    spec_agent = engine._registry.for_type("spec")

    def explode(request: object) -> object:
        raise RuntimeError("gateway down")

    monkeypatch.setattr(spec_agent, "execute", explode)
    run = service.start_run(
        "doomed-task",
        "vhpc",
        inputs={"spec": {"requirement": "Boom"}},
    )
    service.wait_for_drives()
    view = service.get_workflow(run.id)
    assert view is not None and view["status"] == "FAILED"
    assert view["error"]["code"] == "AGENT_EXECUTION_FAILED"
    assert view["error"]["message"] == "Agent raised outside its result contract"
    assert view["error"]["category"] == "AGENT"
    assert view["error"]["at"]

    monkeypatch.undo()
    healthy = service.start_run(
        "healthy-task",
        "vhpc",
        inputs={"spec": {"requirement": "Fine"}},
    )
    view = service.get_workflow(healthy.id)
    assert view is not None and view["error"] is None


def test_run_failing_in_code_fix_keeps_its_approval_gates_done(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    # Dong's messenger case: he approved all three gates, the run
    # reached the review/fix loop and died there — yet the timeline
    # showed every approval as Pending. The run ends in CODE_FIX, a
    # stage no workflow step generates, so the gates' trail lookup
    # found no position and fell back to pending.
    from datetime import datetime

    from asf.contracts.models import AgentResult, PlatformError, RunMetrics

    service, engine, _store = build_demo(tmp_path, ephemeral=True)
    review_agent = engine._registry.for_type("review")
    original_review = review_agent.execute

    def request_changes(request: object) -> object:
        result = original_review(request)
        if result.status == "SUCCESS":
            # The engine cross-checks the output verdict against the
            # CODE_REVIEW artifact's content verdict, so flip both.
            artifact = result.artifacts[0]
            content = {
                **artifact.content,
                "review": {
                    **artifact.content["review"],
                    "verdict": "CHANGES_REQUESTED",
                },
            }
            result = result.model_copy(
                update={
                    "output": {**result.output, "verdict": "CHANGES_REQUESTED"},
                    "artifacts": [artifact.model_copy(update={"content": content})],
                }
            )
        return result

    monkeypatch.setattr(review_agent, "execute", request_changes)
    fix_agent = engine._registry.for_type("fix")
    fix_inputs: list[dict[str, Any]] = []

    def broken_fix(request: object) -> object:
        fix_inputs.append(dict(request.input))
        return AgentResult(
            request_id=request.request_id,
            agent_id=request.agent_id,
            status="FAILED",
            metrics=RunMetrics(
                duration_seconds=0.0,
                revision_count=0,
                attempt=1,
            ),
            errors=[
                PlatformError(
                    code="LLM_INVALID_RESPONSE",
                    message="Invalid replacement ChangeSet",
                    category="LLM",
                    retryable=False,
                    timestamp=datetime.now(UTC),
                    details={"cause": "Invalid JSON: Expecting value at line 1"},
                )
            ],
        )

    monkeypatch.setattr(fix_agent, "execute", broken_fix)
    run = service.start_run(
        "fix-doomed",
        "vhpc",
        inputs={"spec": {"requirement": "Fix loop"}},
    )
    for _ in range(8):
        service.wait_for_drives()
        pending = service.list_approvals()
        if pending:
            service.decide_approval(pending[0]["id"], decision="APPROVE")
            continue
        if engine.get(run.id).state.stage == "FAILED":
            break
    service.wait_for_drives()
    view = service.get_workflow(run.id)
    assert view is not None and view["status"] == "FAILED"
    assert view["error"]["message"] == "Invalid replacement ChangeSet"
    states = {step["id"]: step["state"] for step in view["steps"]}
    assert states["spec_approval"] == "done"
    assert states["plan_approval"] == "done"
    assert states["task_approval"] == "done"
    assert states["implementation"] == "done"
    assert states["code_review"] == "failed"
    assert states["testing"] == "pending"
    assert states["ci"] == "pending"
    assert states["merge"] == "pending"
    # The first fix attempt had no predecessor to learn from.
    assert len(fix_inputs) == 1
    assert "previousFixError" not in fix_inputs[0]

    # Resume re-enters the fix loop and fails the same way; the gates
    # must STILL read done on the fork, and the new attempt must be
    # told why the previous one was rejected — otherwise Resume just
    # replays the identical failure, as it did for Dong.
    resumed = service.resume_run(run.id)
    assert resumed is not None
    service.wait_for_drives()
    view = service.get_workflow(resumed["id"])
    assert view is not None and view["status"] == "FAILED"
    states = {step["id"]: step["state"] for step in view["steps"]}
    assert states["spec_approval"] == "done"
    assert states["plan_approval"] == "done"
    assert states["task_approval"] == "done"
    assert states["code_review"] == "failed"
    assert len(fix_inputs) == 2
    assert "Invalid replacement ChangeSet" in fix_inputs[1]["previousFixError"]
    assert "Invalid JSON" in fix_inputs[1]["previousFixError"]


def test_start_run_returns_while_a_step_is_still_executing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """A slow or hung model call must not block the triggering request.

    Regression: drives ran on the request thread, so one stuck agent
    call froze the whole API — every dashboard list stuck at Loading.
    """
    service, engine, _store = build_demo(tmp_path, ephemeral=True)
    spec_agent = engine._registry.for_type("spec")
    original = spec_agent.execute
    gate = threading.Event()

    def blocking(request: object) -> object:
        gate.wait(timeout=30)  # failsafe: never hang the suite forever
        return original(request)

    monkeypatch.setattr(spec_agent, "execute", blocking)
    run = service.start_run(
        "slow-task",
        "vhpc",
        inputs={"spec": {"requirement": "Slow model"}},
    )
    # start_run returned while the spec agent is still blocked, and the
    # API can still serve the run's (RUNNING) view in the meantime.
    view = service.get_workflow(run.id)
    assert view is not None and view["status"] == "RUNNING"
    gate.set()
    service.wait_for_drives()
    view = service.get_workflow(run.id)
    assert view is not None and view["status"] == "WAITING_APPROVAL"


def test_configure_logging_is_idempotent() -> None:
    import logging

    from asf.api.demo import configure_logging

    logger = logging.getLogger("asf")
    before = list(logger.handlers)
    level, propagate = logger.level, logger.propagate
    try:
        configure_logging()
        configure_logging()
        added = [h for h in logger.handlers if h not in before]
        assert len(added) == 1  # one console handler, not two
    finally:
        for handler in list(logger.handlers):
            if handler not in before:
                logger.removeHandler(handler)
        logger.setLevel(level)
        logger.propagate = propagate
        if hasattr(logger, "_asf_console_configured"):
            delattr(logger, "_asf_console_configured")


def test_startup_recovers_a_run_left_mid_dispatch(tmp_path: Path):
    """A backend stopped mid-dispatch leaves ``in_flight`` set; startup
    recovers it (nothing can be in flight in a fresh process) and the
    run continues on its own instead of stranding at RUNNING forever.
    """
    service, engine, store = build_demo(tmp_path, ephemeral=True)
    run = engine.start(
        task_id="wedged-task",
        project_id="vhpc",
        inputs={"spec": {"requirement": "Heal me"}},
    )
    service.track(run.id)
    wedged = engine.get(run.id)
    wedged.in_flight = "interrupted-dispatch"
    store.save_execution(wedged)

    service.drive_active_runs()
    service.wait_for_drives()
    view = service.get_workflow(run.id)
    assert view is not None and view["status"] == "WAITING_APPROVAL"
    assert engine.get(run.id).in_flight is None


def test_profile_sandbox_settings_extraction(monkeypatch):
    from asf.api.demo import _profile_sandbox_settings
    from asf.configuration.errors import ConfigError

    assert _profile_sandbox_settings(make_profile()) is None

    monkeypatch.setenv("MY_PROJECT_FLAG", "from-env")
    profile = make_profile(
        configuration={
            "testEnv": {"LITERAL": "yes", "REFERENCED": {"env": "MY_PROJECT_FLAG"}},
            "testEnvAllowlist": ["JAVA_HOME"],
            "sandboxLimits": {"cpuSeconds": 60, "maxProcesses": 16},
        }
    )
    settings = _profile_sandbox_settings(profile)
    assert settings is not None
    assert settings.env_extra == {"LITERAL": "yes", "REFERENCED": "from-env"}
    assert settings.env_allowlist == ("JAVA_HOME",)
    assert settings.resource_limits is not None
    assert settings.resource_limits.cpu_seconds == 60
    assert settings.resource_limits.memory_bytes is None
    assert settings.resource_limits.max_processes == 16

    # A missing {env: NAME} reference fails loudly (secret convention).
    monkeypatch.delenv("MY_PROJECT_FLAG")
    with pytest.raises(ConfigError):
        _profile_sandbox_settings(profile)

    with pytest.raises(ValueError):
        _profile_sandbox_settings(
            make_profile(
                configuration={"sandboxLimits": {"cpuSeconds": -1}},
            )
        )
