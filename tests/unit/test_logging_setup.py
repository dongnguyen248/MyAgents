"""Persistent backend logging: file, context, redaction, fallback.

``asf.logging_setup`` configures the ``asf`` logger — console always,
a rotating file when a directory is supplied — and stamps every line
with the log context (run/task/agent/request) that agent execution
sets from its request. A failed run's evidence must survive in
``data/logs/asf.log``; a secret-shaped string must never reach it.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import pytest

import asf
from asf.agents._shared.log_context import log_context
from asf.agents.base import AgentRuntime, BaseAgent, Issue
from asf.contracts.models import AgentMetadata, AgentRequest, Artifact
from asf.logging_setup import configure_logging
from asf.models.fake import ScriptedModelGateway

_STATE_ATTRS = ("_asf_console_configured", "_asf_file_results")


@pytest.fixture
def asf_logger() -> Iterator[logging.Logger]:
    """The ``asf`` logger, with its global state restored afterwards."""
    logger = logging.getLogger("asf")
    handlers = list(logger.handlers)
    level, propagate = logger.level, logger.propagate
    attrs = {name: getattr(logger, name) for name in _STATE_ATTRS if hasattr(logger, name)}
    yield logger
    for handler in list(logger.handlers):
        if handler not in handlers:
            logger.removeHandler(handler)
            handler.close()
    logger.setLevel(level)
    logger.propagate = propagate
    for name in _STATE_ATTRS:
        if name in attrs:
            setattr(logger, name, attrs[name])
        elif hasattr(logger, name):
            delattr(logger, name)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_file_created_with_context_and_startup_lines(asf_logger, tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    path = configure_logging(log_dir)
    assert path == log_dir / "asf.log"
    assert path.is_file()
    with log_context(run_id="run-1", task="task-1", agent="agent-spec", request_id="req-1"):
        logging.getLogger("asf.unit").info("agent is working")
    content = _read(path)
    assert "[run=run-1 task=task-1 agent=agent-spec request=req-1]" in content
    assert "agent is working" in content
    assert f"version={asf.__version__}" in content
    assert f"log file={path}" in content


def test_context_defaults_to_dashes_and_resets(asf_logger, tmp_path: Path) -> None:
    path = configure_logging(tmp_path)
    probe = logging.getLogger("asf.unit")
    probe.info("outside")
    with log_context(run_id="run-9"):
        probe.info("inside")
    probe.info("outside again")
    lines = [line for line in _read(path).splitlines() if "outside" in line or "inside" in line]
    assert "[run=- task=- agent=- request=-]" in lines[0]
    assert "[run=run-9 task=- agent=- request=-]" in lines[1]
    assert "[run=- task=- agent=- request=-]" in lines[2]


def test_secret_shaped_text_never_reaches_the_file(asf_logger, tmp_path: Path) -> None:
    path = configure_logging(tmp_path)
    secret = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    logging.getLogger("asf.unit").warning("call failed for token %s today", secret)
    content = _read(path)
    assert secret not in content
    assert "[REDACTED]" in content


def test_rotation_at_a_tiny_max_size(asf_logger, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ASF_LOG_MAX_BYTES", "400")
    monkeypatch.setenv("ASF_LOG_BACKUPS", "2")
    path = configure_logging(tmp_path)
    probe = logging.getLogger("asf.unit")
    for index in range(30):
        probe.info("rotation probe line %02d with some extra text", index)
    assert (tmp_path / "asf.log.1").is_file()
    assert path.is_file()


def test_file_failure_falls_back_to_console(asf_logger, tmp_path: Path) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    captured: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record)

    capture = _Capture()
    asf_logger.addHandler(capture)
    try:
        path = configure_logging(blocker / "logs")
    finally:
        asf_logger.removeHandler(capture)
    assert path is None
    warnings = [r for r in captured if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "console logging only" in warnings[0].getMessage()
    assert any(type(h) is logging.StreamHandler for h in asf_logger.handlers)


def test_setup_is_idempotent(asf_logger, tmp_path: Path) -> None:
    first = configure_logging(tmp_path)
    handlers_after_first = list(asf_logger.handlers)
    second = configure_logging(tmp_path)
    assert first == second
    assert asf_logger.handlers == handlers_after_first
    file_handlers = [h for h in asf_logger.handlers if isinstance(h, RotatingFileHandler)]
    assert len(file_handlers) == 1


def test_env_log_dir_overrides_the_argument(asf_logger, tmp_path: Path, monkeypatch) -> None:
    env_dir = tmp_path / "from-env"
    monkeypatch.setenv("ASF_LOG_DIR", str(env_dir))
    path = configure_logging(tmp_path / "from-arg")
    assert path == env_dir / "asf.log"
    assert path.is_file()


def test_dotenv_path_is_a_startup_line(asf_logger, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    path = configure_logging(tmp_path, dotenv_path=env_file)
    assert f"Loaded environment from {env_file}" in _read(path)


class _ProbeAgent(BaseAgent):
    """The smallest agent: logs one line from inside its execution."""

    @property
    def metadata(self) -> AgentMetadata:
        return AgentMetadata(
            id="test-agent",
            name="Test Agent",
            type="test",
            version="1.0.0",
            status="IDLE",
            capabilities=["testing"],
            configuration={},
        )

    def _check(self, request: AgentRequest) -> list[Issue]:
        return []

    def _run(self, request: AgentRequest) -> tuple[Any, list[Artifact]]:
        logging.getLogger("asf.probe").info("probe inside execution")
        return ({"summary": "probe ok"}, [])


def test_agent_execution_carries_the_context(asf_logger, tmp_path: Path) -> None:
    path = configure_logging(tmp_path)
    runtime = AgentRuntime(
        models=ScriptedModelGateway([]),
        clock=lambda: datetime.now(UTC),
        new_id=lambda: "id-1",
    )
    request = AgentRequest(
        request_id="req-1",
        task_id="task-1",
        project_id="proj-1",
        workflow_id="software-development",
        agent_id="test-agent",
        input={"requirement": "anything"},
        metadata={"runId": "run-42"},
    )
    _ProbeAgent(runtime).execute(request)
    logging.getLogger("asf.probe").info("probe after execution")
    content = _read(path)
    inside = next(line for line in content.splitlines() if "probe inside" in line)
    assert "[run=run-42 task=task-1 agent=test-agent request=req-1]" in inside
    after = next(line for line in content.splitlines() if "probe after" in line)
    assert "[run=- task=- agent=- request=-]" in after
