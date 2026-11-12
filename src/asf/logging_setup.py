"""Backend logging: console + a persistent, redacted log file.

One configuration point for the ``asf`` logger (used by
``asf.api.demo``): a console handler always, and — when a log
directory is supplied, as the serving entry point does — a rotating
file handler (``asf.log``, 10 MB × 10 backups by default) so the
evidence of a failed run survives the terminal it was printed to.
Configuration comes from the environment: ``ASF_LOG_DIR`` overrides
the directory, ``ASF_LOG_LEVEL`` the level (default INFO),
``ASF_LOG_MAX_BYTES`` / ``ASF_LOG_BACKUPS`` the rotation.

Every emitted line carries the current log context — run, task,
agent and request ids — in a ``[run=… task=… agent=… request=…]``
segment, fed by :mod:`asf.agents._shared.log_context` (agent
execution sets it from the request). Fields with no value render as
``-``. A redacting formatter runs
:func:`asf.agents._shared.security.redact_text` over every finished
line as a last-line safety net: whatever a call site put into a
message, a credential-shaped string does not reach the console or
the file. Call sites still never log prompts, model output,
request/response bodies, keys or Authorization headers.

A file handler that cannot be created (read-only directory, disk
full) never stops the backend: configuration falls back to console
only and emits one WARNING. Setup is idempotent — repeated calls add
no duplicate handlers.

Rotation assumes a single backend process per log file. On Windows
a second process (or a viewer) holding ``asf.log`` open can make the
rename at rotation time fail; run one backend per log directory.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

import asf
from asf.agents._shared.log_context import log_context_values
from asf.agents._shared.security import redact_text

__all__ = ["configure_logging"]

LOG_FILE_NAME = "asf.log"
DEFAULT_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_BACKUPS = 10
_FORMAT = (
    "%(asctime)s %(levelname)s %(name)s "
    "[run=%(run_id)s task=%(task)s agent=%(agent)s request=%(request_id)s]: "
    "%(message)s"
)
_ATTRIBUTES = ("run_id", "task", "agent", "request_id")


class _ContextFilter(logging.Filter):
    """Stamp the current log-context fields onto every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        for attribute, value in zip(_ATTRIBUTES, log_context_values(), strict=True):
            setattr(record, attribute, value)
        return True


class _RedactingFormatter(logging.Formatter):
    """Format as usual, then redact secret-shaped spans in the line.

    Redacting the finished line (not just the message) also covers
    an exception rendered below it by the base formatter.
    """

    def format(self, record: logging.LogRecord) -> str:
        return redact_text(super().format(record))


def _level_name() -> str:
    return os.environ.get("ASF_LOG_LEVEL", "INFO").upper()


def _env_int(name: str, default: int) -> int:
    """A positive int from the environment, else the default."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _handler(handler: logging.Handler) -> logging.Handler:
    handler.setFormatter(_RedactingFormatter(_FORMAT))
    handler.addFilter(_ContextFilter())
    return handler


def _add_console(logger: logging.Logger) -> None:
    if getattr(logger, "_asf_console_configured", False):
        return
    logger.addHandler(_handler(logging.StreamHandler()))
    logger.setLevel(_level_name())
    logger.propagate = False
    logger._asf_console_configured = True  # type: ignore[attr-defined]


def _resolve_dir(log_dir: Path) -> Path:
    override = os.environ.get("ASF_LOG_DIR")
    return Path(override) if override else log_dir


def _add_file(logger: logging.Logger, log_dir: Path) -> Path | None:
    """Attach the rotating file handler once per directory.

    Returns the log file path, or None when the handler could not
    be created — the failure is warned about exactly once per
    directory and never raised. Repeat calls return the first
    call's outcome for that directory.
    """
    directory = _resolve_dir(log_dir)
    results: dict[str, Path | None] = getattr(logger, "_asf_file_results", {})
    if str(directory) in results:
        return results[str(directory)]
    logger._asf_file_results = results  # type: ignore[attr-defined]
    try:
        directory.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            directory / LOG_FILE_NAME,
            maxBytes=_env_int("ASF_LOG_MAX_BYTES", DEFAULT_MAX_BYTES),
            backupCount=_env_int("ASF_LOG_BACKUPS", DEFAULT_BACKUPS),
            encoding="utf-8",
        )
    except OSError as error:
        logger.warning("Could not open log file in %s (%s); console logging only", directory, error)
        results[str(directory)] = None
        return None
    logger.addHandler(_handler(handler))
    results[str(directory)] = directory / LOG_FILE_NAME
    return results[str(directory)]


def _startup_lines(
    logger: logging.Logger, file_path: Path | None, dotenv_path: Path | None
) -> None:
    logger.info(
        "ASF backend logging: version=%s level=%s log file=%s",
        asf.__version__,
        _level_name(),
        file_path if file_path is not None else "none (console only)",
    )
    if dotenv_path is not None:
        logger.info("Loaded environment from %s", dotenv_path)


def configure_logging(
    log_dir: Path | None = None, *, dotenv_path: Path | None = None
) -> Path | None:
    """Configure the ``asf`` logger (console always, file on request).

    Agent failures and provider errors otherwise surface only as a
    one-line dashboard banner; the recorded causes (which model was
    sent, why a reply was rejected) are logged under the ``asf``
    namespace and would go nowhere without a handler. With
    ``log_dir`` (the serving entry point passes ``<data>/logs``) the
    lines also land in a rotating file there; the file's path is
    returned (None when no file logging was requested or it could
    not be set up). Idempotent: repeat calls add no handlers.
    """
    logger = logging.getLogger("asf")
    _add_console(logger)
    if log_dir is None:
        return None
    file_path = _add_file(logger, log_dir)
    _startup_lines(logger, file_path, dotenv_path)
    return file_path
