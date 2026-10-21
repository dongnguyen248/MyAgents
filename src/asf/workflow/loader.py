from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from asf.configuration.errors import ConfigError, ConfigIssue
from asf.configuration.loader import validation_error_to_config_error
from asf.configuration.yamlio import load_yaml_mapping, scan_secrets
from asf.workflow.definition import WorkflowDefinition


def load_workflow(path: str | Path) -> WorkflowDefinition:
    file_path = Path(path)
    if not file_path.is_file():
        raise ConfigError(
            f"Workflow file '{path}' does not exist",
            source=str(path),
        )

    data = load_yaml_mapping(file_path, source=str(file_path))

    expected_id = file_path.stem
    declared_id = data.get("id")
    if declared_id is None:
        data["id"] = expected_id
    elif declared_id != expected_id:
        msg = f"Workflow ID '{declared_id}' does not match file stem '{expected_id}'"
        raise ConfigError(
            f"Workflow ID '{declared_id}' in '{file_path}' "
            f"does not match file stem '{expected_id}'",
            issues=[ConfigIssue(path="id", message=msg)],
            source=str(file_path),
        )

    secret_issues = scan_secrets(data)
    if secret_issues:
        raise ConfigError(
            issues=secret_issues,
            source=str(file_path),
        )

    try:
        return WorkflowDefinition.model_validate(data)
    except ValidationError as exc:
        raise validation_error_to_config_error(exc, source=str(file_path)) from exc


def load_workflows(directory: str | Path) -> dict[str, WorkflowDefinition]:
    dir_path = Path(directory)
    if not dir_path.is_dir():
        raise ConfigError(
            f"Workflows directory '{directory}' does not exist",
            source=str(directory),
        )

    files = sorted(
        [
            p
            for p in dir_path.iterdir()
            if p.is_file() and p.suffix.lower() in {".yaml", ".yml"}
        ]
    )

    workflows: dict[str, WorkflowDefinition] = {}
    for p in files:
        wf = load_workflow(p)
        if wf.id in workflows:
            raise ConfigError(
                f"Duplicate workflow ID '{wf.id}' found in '{p}'",
                issues=[
                    ConfigIssue(
                        path="id",
                        message=f"Duplicate workflow ID '{wf.id}'",
                    )
                ],
                source=str(p),
            )
        workflows[wf.id] = wf

    return workflows
