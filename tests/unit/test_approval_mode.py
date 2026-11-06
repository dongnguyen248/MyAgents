"""Phase 12: approval-mode parsing, validation and precedence."""

from __future__ import annotations

import pytest

from asf.approval.mode import parse_approval_overrides, resolve_approval_mode
from asf.configuration.errors import ConfigError
from asf.workflow.definition import WorkflowStepDef


def _step(**extra: object) -> WorkflowStepDef:
    raw: dict[str, object] = {
        "id": "task",
        "name": "Break down tasks",
        "type": "AGENT",
        "stage": "TASK",
        "agentType": "task",
        "requiresApproval": True,
    }
    raw.update(extra)
    return WorkflowStepDef.model_validate(raw)


def test_resolver_defaults_match_workflow_parse_defaults() -> None:
    # approval.mode must not import asf.workflow (purity guard), so its
    # default constants mirror the definition package's; pin them equal.
    from asf.approval.mode import DEFAULT_AI_MAX_REVISIONS as MODE_AI
    from asf.approval.mode import DEFAULT_HUMAN_MAX_REVISIONS as MODE_HUMAN
    from asf.workflow.definition import DEFAULT_AI_MAX_REVISIONS as DEF_AI
    from asf.workflow.definition import DEFAULT_MAX_REVISIONS as DEF_HUMAN

    assert MODE_AI == DEF_AI
    assert MODE_HUMAN == DEF_HUMAN


def test_defaults_are_human_with_three_revisions() -> None:
    resolved = resolve_approval_mode(_step(), None)
    assert resolved.mode == "human"
    assert resolved.max_revisions == 3
    assert resolved.on_exhausted == "escalate"
    assert resolved.block_on == ("BLOCKER", "MAJOR")


def test_step_block_mode_ai_defaults_to_four_revisions() -> None:
    resolved = resolve_approval_mode(_step(approval={"mode": "ai"}), None)
    assert resolved.mode == "ai"
    assert resolved.max_revisions == 4


def test_step_explicit_max_revisions_wins_over_ai_default() -> None:
    step = _step(approval={"mode": "ai", "maxRevisions": 6})
    assert resolve_approval_mode(step, None).max_revisions == 6
    step = _step(maxRevisions=2)
    assert resolve_approval_mode(step, None).max_revisions == 2


def test_project_overrides_step() -> None:
    step = _step(approval={"mode": "ai", "maxRevisions": 4})
    resolved = resolve_approval_mode(step, {"mode": "human", "maxRevisions": 2})
    assert resolved.mode == "human"
    assert resolved.max_revisions == 2


def test_project_mode_ai_without_max_uses_ai_default() -> None:
    resolved = resolve_approval_mode(_step(), {"mode": "ai"})
    assert resolved.mode == "ai"
    assert resolved.max_revisions == 4


def test_per_stage_beats_project_and_step() -> None:
    step = _step(approval={"mode": "ai", "maxRevisions": 4})
    profile = {"mode": "human", "maxRevisions": 2, "perStage": {"task": {"maxRevisions": 5}}}
    resolved = resolve_approval_mode(step, profile)
    assert resolved.mode == "human"
    assert resolved.max_revisions == 5


def test_per_stage_mode_beats_project_mode() -> None:
    profile = {"mode": "human", "perStage": {"task": {"mode": "none"}}}
    assert resolve_approval_mode(_step(), profile).mode == "none"


def test_on_exhausted_and_block_on_resolution() -> None:
    profile = {"onExhausted": "accept_with_warnings", "blockOn": ["MAJOR", "MINOR"]}
    resolved = resolve_approval_mode(_step(), profile)
    assert resolved.on_exhausted == "accept_with_warnings"
    assert resolved.block_on == ("BLOCKER", "MAJOR", "MINOR")


def test_blocker_is_always_blocking() -> None:
    resolved = resolve_approval_mode(_step(), {"blockOn": ["MINOR"]})
    assert resolved.block_on == ("BLOCKER", "MINOR")
    resolved = resolve_approval_mode(_step(), {"blockOn": []})
    assert resolved.block_on == ("BLOCKER",)


def test_parse_accepts_snake_case_keys() -> None:
    overrides = parse_approval_overrides({"max_revisions": 3, "on_exhausted": "escalate"})
    assert overrides.max_revisions == 3
    assert overrides.on_exhausted == "escalate"


@pytest.mark.parametrize(
    "approval",
    [
        {"mode": "robot"},
        {"maxRevisions": 0},
        {"maxRevisions": 11},
        {"maxRevisions": "four"},
        {"onExhausted": "shrug"},
        {"blockOn": ["CRITICAL"]},
        {"blockOn": "BLOCKER"},
        {"perStage": ["task"]},
        {"perStage": {"task": "soon"}},
        {"perStage": {"task": {"maxRevisions": 99}}},
    ],
)
def test_invalid_profile_keys_raise_config_error(approval: dict) -> None:
    with pytest.raises(ConfigError):
        parse_approval_overrides(approval)
    with pytest.raises(ConfigError):
        resolve_approval_mode(_step(), approval)
