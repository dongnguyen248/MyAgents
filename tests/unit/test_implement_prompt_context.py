from __future__ import annotations

import json
import logging

import pytest

from asf.agents.implement.prompts import (
    ImplementPromptContext,
    ImplementPrompts,
    build_implement_messages,
)


def build_messages(project_context):
    return build_implement_messages(
        ImplementPromptContext(
            prompts=ImplementPrompts(system="system"),
            spec_artifact={},
            plan_artifact={},
            task_artifact={},
            task_item_id="T1",
            existing_files={},
            language=None,
            project_context=project_context,
        )
    )


@pytest.mark.parametrize(
    "project_context",
    ["{bad json", "[]", '{"enabledSkills": [1]}', {"enabledSkills": ["testing"]}],
)
def test_invalid_or_mapping_project_context_logs_and_omits_skills(project_context, caplog):
    with caplog.at_level(logging.WARNING):
        messages = build_messages(project_context)

    assert messages[0].content == "system"
    assert "project context" in caplog.text.lower()


def test_valid_json_project_context_includes_skills():
    messages = build_messages('{"enabledSkills": ["testing"]}')

    assert messages[0].content == "system\nEnabled skills: testing"


def test_unexpected_json_parser_error_is_not_swallowed(monkeypatch):
    def fail(_value):
        raise RuntimeError("unexpected parser failure")

    monkeypatch.setattr(json, "loads", fail)
    with pytest.raises(RuntimeError, match="unexpected parser failure"):
        build_messages('{"enabledSkills": ["testing"]}')
