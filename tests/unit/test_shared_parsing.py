from __future__ import annotations

import pytest

from asf.agents._shared.parsing import ParseError, parse_json, strip_code_fence


def _taskagent_strip_fence(text: str) -> str:
    """Replicate TaskAgent's inline fence unwrapping logic for parity testing."""
    text = text.strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].strip() == "```":
            return "\n".join(lines[1:-1]).strip()
    return text


def test_task_agent_fence_parity_no_fence() -> None:
    for text in ["plain text", "  plain text  "]:
        shared = strip_code_fence(text)
        taskagent = _taskagent_strip_fence(text)
        assert shared == taskagent == text.strip()


def test_task_agent_fence_parity_fence_with_language() -> None:
    text = "```python\nprint('hello')\n```"
    shared = strip_code_fence(text)
    taskagent = _taskagent_strip_fence(text)
    assert shared == taskagent == "print('hello')"


def test_task_agent_fence_parity_fence_without_language() -> None:
    text = "```\nprint('hello')\n```"
    shared = strip_code_fence(text)
    taskagent = _taskagent_strip_fence(text)
    assert shared == taskagent == "print('hello')"


def test_task_agent_fence_parity_fence_with_extra_whitespace() -> None:
    text = "  ```python\nprint('hello')\n```  "
    shared = strip_code_fence(text)
    taskagent = _taskagent_strip_fence(text)
    assert shared == taskagent == "print('hello')"


def test_task_agent_fence_parity_multiline_content() -> None:
    text = "```python\ndef foo():\n    return 42\n```"
    shared = strip_code_fence(text)
    taskagent = _taskagent_strip_fence(text)
    assert shared == taskagent == "def foo():\n    return 42"


def test_task_agent_fence_parity_not_full_wrap() -> None:
    # TaskAgent only unwraps if entire text starts and ends with ```
    text = "```python\nprint('hello')\n``` extra text"
    shared = strip_code_fence(text)
    taskagent = _taskagent_strip_fence(text)
    # TaskAgent won't unwrap this (doesn't end with ```)
    assert taskagent == text.strip()
    # strip_code_fence also won't match (regex expects full wrap)
    assert shared == text.strip()


def test_strip_code_fence_no_fence() -> None:
    assert strip_code_fence("plain text") == "plain text"
    assert strip_code_fence("  plain text  ") == "plain text"


def test_strip_code_fence_fence_with_language() -> None:
    text = "```python\nprint('hello')\n```"
    assert strip_code_fence(text) == "print('hello')"


def test_strip_code_fence_fence_without_language() -> None:
    text = "```\nprint('hello')\n```"
    assert strip_code_fence(text) == "print('hello')"


def test_strip_code_fence_fence_with_extra_whitespace() -> None:
    text = "  ```python\nprint('hello')\n```  "
    assert strip_code_fence(text) == "print('hello')"


def test_strip_code_fence_multiline_content() -> None:
    text = "```python\ndef foo():\n    return 42\n```"
    assert strip_code_fence(text) == "def foo():\n    return 42"


def test_parse_json_valid_json() -> None:
    result = parse_json('{"key": "value", "num": 42}')
    assert result == {"key": "value", "num": 42}


def test_parse_json_valid_json_with_fence() -> None:
    text = """```json
{
  "key": "value"
}
```"""
    result = parse_json(text)
    assert result == {"key": "value"}


def test_parse_json_invalid_json() -> None:
    with pytest.raises(ParseError) as exc:
        parse_json('{"key": "value",}')
    assert "Invalid JSON" in str(exc.value)


def test_parse_json_not_an_object() -> None:
    with pytest.raises(ParseError) as exc:
        parse_json('["a", "b"]')
    assert "JSON root must be an object" in str(exc.value)


def test_parse_json_raw_preserved_in_error() -> None:
    with pytest.raises(ParseError) as exc:
        parse_json('invalid')
    assert exc.value.raw == 'invalid'