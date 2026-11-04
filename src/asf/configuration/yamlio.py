from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any, TextIO

import yaml
from yaml.constructor import ConstructorError

from asf.configuration.errors import ConfigError, ConfigIssue
from asf.configuration.secrets import ENV_VAR_PATTERN

SECRET_KEY_REGEX = re.compile(
    r"(?i)(?:secret|token|password|passwd|api[_-]?key|credentials?)$"
)


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_mapping(
    loader: yaml.Loader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key '{key}'",
                key_node.start_mark,
            )
        value = loader.construct_object(value_node, deep=deep)
        mapping[key] = value
    return mapping


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


def _format_yaml_error(exc: yaml.YAMLError) -> str:
    if isinstance(exc, yaml.MarkedYAMLError):
        pieces: list[str] = []
        if exc.context:
            pieces.append(str(exc.context).strip())
        if exc.problem:
            pieces.append(str(exc.problem).strip())
        mark = exc.problem_mark or exc.context_mark
        if mark:
            pieces.append(f"at line {mark.line + 1}, column {mark.column + 1}")
        if pieces:
            if len(pieces) == 3:
                return f"{pieces[0]}: {pieces[1]} {pieces[2]}"
            if len(pieces) == 2:
                return f"{pieces[0]} {pieces[1]}"
            return pieces[0]
    return "YAML parsing error"


def load_yaml_mapping(
    stream: str | Path | TextIO,
    source: str | None = None,
) -> dict[str, Any]:
    src_name = source

    content: str
    if isinstance(stream, Path):
        src_name = src_name or str(stream)
        try:
            content = stream.read_text(encoding="utf-8")
        except OSError as e:
            raise ConfigError(
                f"Cannot read file '{stream}': {e}",
                source=src_name,
            ) from e
    elif isinstance(stream, str):
        # Could be path or raw yaml content
        try:
            potential_path = Path(stream)
            if potential_path.is_file():
                src_name = src_name or stream
                content = potential_path.read_text(encoding="utf-8")
            else:
                content = stream
        except OSError:
            content = stream
    else:
        content = stream.read()


    try:
        # UniqueKeyLoader extends SafeLoader and only customizes duplicate-key handling.
        data = yaml.load(content, Loader=UniqueKeyLoader)  # nosec B506
    except yaml.YAMLError as exc:
        msg = _format_yaml_error(exc)
        raise ConfigError(
            f"YAML syntax error: {msg}",
            issues=[ConfigIssue(path="", message=msg)],
            source=src_name,
        ) from exc


    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(
            "YAML root must be a mapping",
            issues=[ConfigIssue(path="", message="YAML root must be a mapping")],
            source=src_name,
        )

    return data


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = copy.deepcopy(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def scan_secrets(data: Any, path: str = "") -> list[ConfigIssue]:

    issues: list[ConfigIssue] = []
    if isinstance(data, dict):
        for k, v in data.items():
            k_str = str(k)
            child_path = f"{path}.{k_str}" if path else k_str
            if SECRET_KEY_REGEX.search(k_str):
                # Must be null or {env: NAME}
                is_valid_ref = (
                    v is None
                    or (
                        isinstance(v, dict)
                        and set(v.keys()) == {"env"}
                        and isinstance(v.get("env"), str)
                        and bool(ENV_VAR_PATTERN.match(v["env"]))
                    )
                )
                if not is_valid_ref:
                    msg = (
                        f"Secret key '{k_str}' must be null or {{env: ENV_VAR}}, "
                        "not a literal value"
                    )
                    issues.append(ConfigIssue(path=child_path, message=msg))
            issues.extend(scan_secrets(v, child_path))
    elif isinstance(data, list):
        for idx, item in enumerate(data):
            child_path = f"{path}[{idx}]"
            issues.extend(scan_secrets(item, child_path))
    return issues
