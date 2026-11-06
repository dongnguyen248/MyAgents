"""PR/MR description builder + validator (hosting, Phase 8 + AGENTS.md rule)."""

from __future__ import annotations

from dataclasses import replace

from asf.integrations.hosting.description import (
    SECTION_HEADINGS,
    ChangeRequestDescription,
    ChangeRequestInfo,
    change_request_description,
    render_description,
    validate_description,
)
from asf.tools.changeset import ChangeSet


def _fields() -> ChangeRequestDescription:
    return ChangeRequestDescription(
        summary="Add a thing",
        changes=("R1: the thing works",),
        why="Users need the thing; today it is missing.",
        how=("`src/thing.py` - created the thing",),
        verification=("`pytest -q` - 10 passed",),
        risk="Two-way door: additive only.",
        blast_radius="the thing module only",
        rollback="revert the commit",
    )


def _valid_text() -> str:
    return render_description(_fields())


def test_rendered_description_is_valid_and_ordered() -> None:
    text = _valid_text()
    assert validate_description(text) == []
    positions = [text.index(heading) for heading in SECTION_HEADINGS]
    assert positions == sorted(positions)


def test_missing_heading_is_reported() -> None:
    text = _valid_text().replace("## Why\n", "")
    problems = validate_description(text)
    assert any("missing heading: ## Why" in problem for problem in problems)


def test_duplicated_heading_is_reported() -> None:
    text = _valid_text() + "\n## Why\nAgain.\n"
    problems = validate_description(text)
    assert any("duplicated heading: ## Why" in problem for problem in problems)


def test_reordered_headings_are_reported() -> None:
    text = _valid_text()
    why_at = text.index("## Why")
    how_at = text.index("## How")
    reordered = text[:why_at] + text[how_at:] + text[why_at:how_at]
    problems = validate_description(reordered)
    assert any("out of order" in problem for problem in problems)


def test_empty_section_is_reported() -> None:
    text = _valid_text().replace("Users need the thing; today it is missing.\n", "")
    problems = validate_description(text)
    assert any("empty section: ## Why" in problem for problem in problems)


def test_html_comment_and_placeholders_are_reported() -> None:
    text = _valid_text().replace("Add a thing", "Add a thing <!-- fill in -->")
    problems = validate_description(text)
    assert any("HTML comment" in problem for problem in problems)
    text = _valid_text().replace("Add a thing", "TODO: name the thing")
    problems = validate_description(text)
    assert any("TODO" in problem for problem in problems)
    text = _valid_text().replace("Add a thing", "TBD")
    problems = validate_description(text)
    assert any("TBD" in problem for problem in problems)


def test_verification_needs_a_command_or_an_honest_not_run() -> None:
    text = render_description(replace(_fields(), verification=("Checked it thoroughly.",)))
    problems = validate_description(text)
    assert any("Verification" in problem for problem in problems)
    honest = render_description(
        replace(
            _fields(),
            verification=("Automated tests: not run - no test setup in this repo",),
        )
    )
    assert validate_description(honest) == []


def test_bot_summary_heading_is_reported() -> None:
    text = _valid_text() + "\n## Summary\nGenerated summary.\n"
    problems = validate_description(text)
    assert any("unexpected heading" in problem for problem in problems)


def test_missing_security_impact_line_is_reported() -> None:
    text = _valid_text().replace("Security impact: none\n", "")
    problems = validate_description(text)
    assert any("Security impact" in problem for problem in problems)
    empty = _valid_text().replace("Security impact: none", "Security impact:")
    problems = validate_description(empty)
    assert any("Security impact" in problem for problem in problems)


def _info(test_commands: tuple[str, ...] = ()) -> ChangeRequestInfo:
    return ChangeRequestInfo(
        title="Build the thing",
        task_id="task-1",
        run_id="run-1",
        branch="asf/task-1",
        base_branch="main",
        test_commands=test_commands,
    )


def _changeset(*changes: dict[str, str]) -> ChangeSet:
    return ChangeSet.model_validate({"changes": list(changes)})


def test_built_description_validates_and_names_every_file() -> None:
    changes = _changeset(
        {"path": "a.py", "operation": "create", "content": "a = 1\n"},
        {"path": "b.py", "operation": "modify", "content": "b = 2\n"},
        {"path": "c.py", "operation": "delete"},
    )
    text = render_description(change_request_description(_info(), changes))
    assert validate_description(text) == []
    for path in ("a.py", "b.py", "c.py"):
        assert f"`{path}`" in text
    assert "1 created, 1 modified, 1 deleted" in text
    assert "not run" in text


def test_built_description_cites_configured_test_commands() -> None:
    info = _info(("python -m pytest -q",))
    changes = _changeset({"path": "a.py", "operation": "create", "content": "a = 1\n"})
    text = render_description(change_request_description(info, changes))
    assert validate_description(text) == []
    assert "`python -m pytest -q` - passed in this run's test step" in text


def test_built_description_security_impact_reflects_the_changeset() -> None:
    plain = _changeset({"path": "a.py", "operation": "create", "content": "a = 1\n"})
    text = render_description(change_request_description(_info(), plain))
    assert "Security impact: none" in text
    sensitive = _changeset(
        {"path": "src/auth/session.py", "operation": "modify", "content": "b = 2\n"}
    )
    text = render_description(change_request_description(_info(), sensitive))
    assert validate_description(text) == []
    assert "Security impact: review required" in text
    assert "auth" in text and "session" in text


def test_built_description_groups_large_change_sets() -> None:
    changes = _changeset(
        *[
            {"path": f"pkg/mod{i}.py", "operation": "create", "content": "x = 1\n"}
            for i in range(25)
        ]
    )
    text = render_description(change_request_description(_info(), changes))
    assert validate_description(text) == []
    assert "`pkg` - 25 file(s): created" in text
