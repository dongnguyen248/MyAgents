from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from pydantic import ValidationError
from pydantic.alias_generators import to_camel

from asf.configuration.errors import ConfigError, ConfigIssue
from asf.configuration.platform import PlatformConfig
from asf.configuration.project import ProjectProfile
from asf.configuration.yamlio import deep_merge, load_yaml_mapping, scan_secrets


def _loc_to_dotted_path(loc: tuple[int | str, ...]) -> str:
    parts: list[str] = []
    for item in loc:
        if isinstance(item, int):
            if parts:
                parts[-1] = f"{parts[-1]}[{item}]"
            else:
                parts.append(f"[{item}]")
        else:
            # Format field names as camelCase for consistency with contracts and YAML
            parts.append(to_camel(str(item)))
    return ".".join(parts)


def validation_error_to_config_error(
    exc: ValidationError,
    source: str | None = None,
) -> ConfigError:
    issues: list[ConfigIssue] = []
    for err in exc.errors():
        path = _loc_to_dotted_path(err.get("loc", ()))
        msg = err.get("msg", "Validation error")
        # Strip Pydantic prefix like "Value error, " if present for cleaner message
        if msg.startswith("Value error, "):
            msg = msg[len("Value error, ") :]
        issues.append(ConfigIssue(path=path, message=msg))
    return ConfigError(issues=issues, source=source)


_validation_error_to_config_error = validation_error_to_config_error


def resolve_config_dir(
    config_dir: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> Path | None:
    env_map = os.environ if environ is None else environ

    if config_dir is not None:
        p = Path(config_dir)
        if not p.is_dir():
            raise ConfigError(
                f"Specified configuration directory '{config_dir}' does not exist",
                source=str(config_dir),
            )
        return p

    if "ASF_CONFIG_DIR" in env_map and env_map["ASF_CONFIG_DIR"]:
        env_dir = env_map["ASF_CONFIG_DIR"]
        p = Path(env_dir)
        if not p.is_dir():
            raise ConfigError(
                f"Configuration directory from ASF_CONFIG_DIR '{env_dir}' does not exist",
                source=env_dir,
            )
        return p

    default_p = Path("./config")
    if default_p.is_dir():
        return default_p

    return None


def load_platform_config(
    config_dir: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> PlatformConfig:
    resolved_dir = resolve_config_dir(config_dir, environ=environ)
    if resolved_dir is None:
        # Defaults only
        try:
            return PlatformConfig()
        except ValidationError as exc:
            raise _validation_error_to_config_error(exc) from exc

    merged_data: dict[str, Any] = {}
    sources: list[str] = []

    platform_yaml = resolved_dir / "platform.yaml"
    if platform_yaml.is_file():
        data = load_yaml_mapping(platform_yaml, source=str(platform_yaml))
        merged_data = deep_merge(merged_data, data)
        sources.append(str(platform_yaml))

    local_yaml = resolved_dir / "platform.local.yaml"
    if local_yaml.is_file():
        data = load_yaml_mapping(local_yaml, source=str(local_yaml))
        merged_data = deep_merge(merged_data, data)
        sources.append(str(local_yaml))

    primary_source = ", ".join(sources) if sources else str(resolved_dir)

    secret_issues = scan_secrets(merged_data)
    if secret_issues:
        raise ConfigError(
            issues=secret_issues,
            source=primary_source,
        )

    try:
        return PlatformConfig.model_validate(merged_data)
    except ValidationError as exc:
        raise _validation_error_to_config_error(exc, source=primary_source) from exc


def load_project(path: str | Path) -> ProjectProfile:
    file_path = Path(path)
    if not file_path.is_file():
        raise ConfigError(f"Project file '{path}' does not exist", source=str(path))

    data = load_yaml_mapping(file_path, source=str(file_path))

    expected_id = file_path.stem
    declared_id = data.get("id")
    if declared_id is None:
        data["id"] = expected_id
    elif declared_id != expected_id:
        raise ConfigError(
            f"Project ID '{declared_id}' in '{file_path}' does not match file stem '{expected_id}'",
            issues=[
                ConfigIssue(
                    path="id",
                    message=f"Project ID '{declared_id}' does not match file stem '{expected_id}'",
                )
            ],
            source=str(file_path),
        )

    secret_issues = scan_secrets(data)
    if secret_issues:
        raise ConfigError(
            issues=secret_issues,
            source=str(file_path),
        )

    try:
        return ProjectProfile.model_validate(data)
    except ValidationError as exc:
        raise _validation_error_to_config_error(exc, source=str(file_path)) from exc


def load_projects(directory: str | Path) -> dict[str, ProjectProfile]:
    dir_path = Path(directory)
    if not dir_path.is_dir():
        raise ConfigError(
            f"Projects directory '{directory}' does not exist",
            source=str(directory),
        )

    files = sorted(
        [
            p
            for p in dir_path.iterdir()
            if p.is_file() and p.suffix.lower() in {".yaml", ".yml"}
        ]
    )

    profiles: dict[str, ProjectProfile] = {}
    for p in files:
        profile = load_project(p)
        if profile.id in profiles:
            raise ConfigError(
                f"Duplicate project ID '{profile.id}' found in '{p}'",
                issues=[
                    ConfigIssue(
                        path="id",
                        message=f"Duplicate project ID '{profile.id}'",
                    )
                ],
                source=str(p),
            )
        profiles[profile.id] = profile

    return profiles
