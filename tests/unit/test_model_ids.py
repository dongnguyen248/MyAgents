"""Model id normalisation/validation (FIX-1 Stage 1).

Providers match ids exactly, so ids pasted from documents must be
cleaned of look-alike characters and checked before they are stored:
dash variants fold to "-", invisible characters are stripped,
visible out-of-charset characters and doubled ids are rejected.
"""

from __future__ import annotations

import logging
import re

import pytest

from asf.api.model_ids import (
    checked_model_id,
    model_id_problem,
    normalize_model_id,
    normalize_stored_model_id,
    repeated_fragment,
)

NBSP = "\u00a0"
NB_HYPHEN = "\u2011"
ZWSP = "\u200b"
BOM = "\ufeff"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("claude-haiku-4.5", "claude-haiku-4.5"),
        ("  claude-haiku-4.5  ", "claude-haiku-4.5"),
        (f"{NBSP}claude-haiku-4.5{NBSP}", "claude-haiku-4.5"),
        (f"claude{NB_HYPHEN}haiku{NB_HYPHEN}4.5", "claude-haiku-4.5"),
        ("claude—haiku", "claude-haiku"),
        (f"{BOM}claude-haiku-4.5", "claude-haiku-4.5"),
        (f"claude-haiku{ZWSP}-4.5", "claude-haiku-4.5"),
        ("claude\x00-haiku\x7f", "claude-haiku"),
        ("openai/gpt-4o", "openai/gpt-4o"),
        ("muse-spark-1.3", "muse-spark-1.3"),
    ],
)
def test_normalize_model_id(raw: str, expected: str) -> None:
    assert normalize_model_id(raw) == expected


def test_bom_is_stripped_even_though_python_strip_keeps_it() -> None:
    # JS trim() removes U+FEFF but Python str.strip() does not; the
    # backend helper is the single source of truth and removes it
    # as an invisible character, at either edge and inside.
    assert f"{BOM}x".strip() == f"{BOM}x"
    assert normalize_model_id(f"{BOM}claude-haiku-4.5{BOM}") == "claude-haiku-4.5"


@pytest.mark.parametrize(
    "model",
    [
        "claude-haiku-4.5",
        "openai/gpt-4o",
        "model-11-11-pro",
        "abab-config-v2",
        "a",
        "",
    ],
)
def test_valid_ids_have_no_problem(model: str) -> None:
    assert model_id_problem(model) is None
    assert checked_model_id("model", model) == model


@pytest.mark.parametrize(
    ("model", "fragment"),
    [
        ("gpt-4.1gpt-4.1", "gpt-4.1"),
        ("abab", "ab"),
        ("xyzxyzxyz", "xyz"),
    ],
)
def test_repeated_fragment_detects_doubled_ids(model: str, fragment: str) -> None:
    assert repeated_fragment(model) == fragment
    problem = model_id_problem(model)
    assert problem is not None
    assert fragment in problem


@pytest.mark.parametrize(
    "model",
    [
        "gpt-4.1gpt-4.1x",
        "abcab",
        "model-11-11",
        "haiku-haiku",
    ],
)
def test_repeated_substrings_that_are_not_doubled_pass(model: str) -> None:
    assert repeated_fragment(model) is None
    assert model_id_problem(model) is None


@pytest.mark.parametrize(
    ("model", "code_point"),
    [
        (f"claude{NBSP}haiku", "U+00A0"),
        ("claude haiku", "U+0020"),
        ("model@home", "U+0040"),
        ("gpt-4.1!", "U+0021"),
        ("модель", "U+043C"),
    ],
)
def test_visible_out_of_charset_characters_are_rejected(
    model: str,
    code_point: str,
) -> None:
    problem = model_id_problem(model)
    assert problem is not None
    assert code_point in problem
    with pytest.raises(ValueError, match=re.escape(code_point)):
        checked_model_id("agentModels.plan", model)


def test_rejection_names_the_field_and_suggests_the_fragment() -> None:
    with pytest.raises(ValueError) as caught:
        checked_model_id("agentModels.review", "gpt-4.1gpt-4.1")
    message = str(caught.value)
    assert "agentModels.review" in message
    assert "'gpt-4.1' alone" in message


def test_case_is_preserved() -> None:
    assert checked_model_id("model", "Claude-Haiku-4.5") == "Claude-Haiku-4.5"
    assert model_id_problem("Claude-Haiku-4.5") is None


def test_stored_id_normalises_and_warns(caplog: pytest.LogCaptureFixture) -> None:
    raw = f"claude{NB_HYPHEN}haiku-4.5"
    with caplog.at_level(logging.WARNING, logger="asf.api.model_ids"):
        cleaned = normalize_stored_model_id("agentModels.plan", raw)
    assert cleaned == "claude-haiku-4.5"
    assert "agentModels.plan" in caplog.text
    assert ascii(raw) in caplog.text


def test_stored_invalid_id_is_kept_and_warns(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="asf.api.model_ids"):
        kept = normalize_stored_model_id("model", "bad@id")
    assert kept == "bad@id"
    assert "invalid" in caplog.text


def test_stored_clean_id_does_not_warn(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="asf.api.model_ids"):
        assert normalize_stored_model_id("model", "gpt-4.1") == "gpt-4.1"
    assert caplog.text == ""
