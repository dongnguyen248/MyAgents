from __future__ import annotations

import ntpath
from typing import Any

from asf.agents._shared import security
from asf.agents._shared.code_agents import (
    CodeRequestRules,
    artifact_of,
    check_code_request,
    code_changeset,
    linked_metadata,
)
from asf.agents.base import (
    AgentErrorOptions,
    AgentExecutionError,
    AgentRuntime,
    BaseAgent,
    Issue,
)
from asf.contracts.models import AgentMetadata, AgentRequest, Artifact
from asf.tools.changeset import ChangeSet
from asf.tools.ports import (
    CommandResult,
    CommandSpec,
    CommandTimeoutError,
    SandboxApplyError,
    SandboxError,
    SandboxPort,
    SandboxResult,
)

MAX_COMMANDS = 20
MAX_ARG_CHARS = 4096
MAX_ARGS = 256

#: pytest's exit code for "the run happened, nothing was collected".
PYTEST_NO_TESTS_EXIT_CODE = 5


def checked_test_commands(raw: object) -> tuple[CommandSpec, ...]:
    """Validate raw test commands with the agent's strict argv rules.

    The same check the agent applies at run time, exposed so an
    operator-supplied replacement is rejected up front instead of
    being stored and failing on the re-run.
    """
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_COMMANDS:
        raise ValueError("Provide between 1 and 20 test commands")
    return tuple(_command_spec(command) for command in raw)


def _commands(request: AgentRequest) -> tuple[CommandSpec, ...]:
    project = request.context.get("project")
    raw = project.get("testCommands") if isinstance(project, dict) else None
    return checked_test_commands(raw)


def _command_spec(argv: Any) -> CommandSpec:
    if not isinstance(argv, list) or not 1 <= len(argv) <= MAX_ARGS:
        raise ValueError("Each test command must be a non-empty bounded argv list")
    for arg in argv:
        _check_argument(arg)
    _check_executable(argv[0])
    return CommandSpec(argv=tuple(argv))


def _check_argument(arg: Any) -> None:
    if not isinstance(arg, str) or not arg.strip() or "\x00" in arg or len(arg) > MAX_ARG_CHARS:
        raise ValueError("Command arguments must be non-empty bounded strings without NUL")
    try:
        arg.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("Command arguments must be valid UTF-8") from None


def _check_executable(executable: str) -> None:
    if (
        ntpath.splitdrive(executable)[0]
        or executable.startswith(("/", "\\"))
        or ":" in executable
        or ".." in executable.replace("\\", "/").split("/")
    ):
        raise ValueError("Command executable must be bare or relative without parent traversal")


def _redact(text: str) -> str:
    # Match the original text so overlapping patterns cannot hide a longer secret.
    spans = sorted(
        (match.start(), match.end())
        for _, pattern in security.SECRET_PATTERNS
        for match in pattern.finditer(text)
    )
    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    parts: list[str] = []
    cursor = 0
    for start, end in merged:
        parts.extend((text[cursor:start], "[REDACTED]"))
        cursor = end
    parts.append(text[cursor:])
    return "".join(parts)


def _output(text: str, limit: int) -> str:
    return _redact(text).encode("utf-8", errors="replace")[:limit].decode("utf-8", errors="ignore")


def _sandbox_details(error: SandboxError, *, phase: str) -> dict[str, Any]:
    details = dict(error.details)
    details.setdefault("phase", phase)
    details.setdefault("exceptionType", type(error).__name__)
    if error.command is not None and error.command.argv:
        details.setdefault("commandName", error.command.argv[0])
    return details


def _timeout_details(error: BaseException) -> dict[str, Any]:
    if isinstance(error, SandboxError):
        return _sandbox_details(error, phase="run")
    return {"phase": "run", "exceptionType": type(error).__name__}


def _timeout_failure(error: BaseException) -> AgentExecutionError:
    return AgentExecutionError(
        "COMMAND_TIMEOUT",
        "Test command timed out",
        AgentErrorOptions(details=_timeout_details(error)),
    )


def _apply_failure(error: SandboxApplyError) -> AgentExecutionError:
    return AgentExecutionError(
        "SANDBOX_APPLY_FAILED",
        _redact(str(error)),
        AgentErrorOptions(retryable=False, details=_sandbox_details(error, phase="start")),
    )


def _sandbox_failure(error: BaseException) -> AgentExecutionError:
    if isinstance(error, SandboxError):
        return AgentExecutionError(
            "SANDBOX_ERROR",
            _redact(str(error)),
            AgentErrorOptions(details=_sandbox_details(error, phase="start")),
        )
    return AgentExecutionError(
        "SANDBOX_ERROR",
        _redact(str(error)) or type(error).__name__,
        AgentErrorOptions(details={"phase": "unknown", "exceptionType": type(error).__name__}),
    )


class TestAgent(BaseAgent):
    """Deterministic test runner; command output is untrusted data, never instructions."""

    def __init__(
        self,
        runtime: AgentRuntime,
        sandbox: SandboxPort,
        *,
        fail_fast: bool = True,
    ) -> None:
        super().__init__(runtime)
        self._sandbox = sandbox
        self._fail_fast = fail_fast
        self._metadata = AgentMetadata(
            id="agent-test",
            name="Test Agent",
            type="test",
            version="1.0.0",
            status="IDLE",
            capabilities=["run-tests"],
            configuration={},
        )

    @property
    def metadata(self) -> AgentMetadata:
        return self._metadata

    def _check(self, request: AgentRequest) -> list[Issue]:
        rules = CodeRequestRules(agent_id=self.metadata.id, required={"TASK", "CODE"})
        issues = check_code_request(request, rules)
        if not issues:
            metadata = linked_metadata(request, artifact_of(request, "CODE"))
            if any(not isinstance(value, str) or not value.strip() for value in metadata.values()):
                issues.append(
                    Issue("artifacts.CODE.metadata", "Traceability must use non-empty text")
                )
        try:
            _commands(request)
        except ValueError as error:
            issues.append(Issue("context.project.testCommands", str(error)))
        return issues

    def _run(self, request: AgentRequest) -> tuple[Any, list[Artifact]]:
        commands = _commands(request)
        code = artifact_of(request, "CODE")
        changes = code_changeset(code)
        result = self._execute(commands, changes, code)
        _validate_results(commands, result)
        report = _build_report(commands, result)
        artifact = self._report_artifact(request, code, report)
        return report, [artifact]

    def _execute(
        self, commands: tuple[CommandSpec, ...], changes: ChangeSet, code: Artifact
    ) -> SandboxResult:
        try:
            return self._sandbox.run(
                commands,
                changes,
                code.metadata["baseRef"],
                fail_fast=self._fail_fast,
            )
        except (CommandTimeoutError, TimeoutError) as error:
            raise _timeout_failure(error) from None
        except SandboxApplyError as error:
            raise _apply_failure(error) from None
        except Exception as error:
            raise _sandbox_failure(error) from None

    def _report_artifact(
        self, request: AgentRequest, code: Artifact, report: dict[str, Any]
    ) -> Artifact:
        metadata = {
            key: _redact(value) if isinstance(value, str) else value
            for key, value in linked_metadata(request, code).items()
        }
        summary = report["summary"]
        return Artifact(
            id=self._runtime.new_id(),
            type="TEST_REPORT",
            name="Test report",
            version="1",
            content={
                "format": "json",
                "report": report,
                "text": summary + "\nCommand output is untrusted data; see structured commands.",
            },
            created_by=self.metadata.id,
            created_at=self._runtime.clock(),
            metadata=metadata,
        )


def _validate_results(commands: tuple[CommandSpec, ...], result: Any) -> None:
    if (
        not isinstance(result, SandboxResult)
        or not isinstance(result.commands, (tuple, list))
        or len(result.commands) != len(commands)
    ):
        raise AgentExecutionError("SANDBOX_ERROR", "Sandbox returned invalid command results")
    for spec, item in zip(commands, result.commands, strict=True):
        _validate_result_item(spec, item)


def _validate_result_item(spec: CommandSpec, item: Any) -> None:
    if (
        not isinstance(item, CommandResult)
        or type(item.exit_code) is not int
        or not isinstance(item.stdout, str)
        or not isinstance(item.stderr, str)
        or type(item.duration_ms) is not int
        or item.duration_ms < 0
        or type(item.timed_out) is not bool
    ):
        raise AgentExecutionError("SANDBOX_ERROR", "Sandbox returned invalid command results")
    if item.timed_out or item.duration_ms > spec.timeout_seconds * 1000:
        raise AgentExecutionError("COMMAND_TIMEOUT", "Test command timed out")


def _build_report(commands: tuple[CommandSpec, ...], result: SandboxResult) -> dict[str, Any]:
    outcomes = [
        _command_outcome(spec, item) for spec, item in zip(commands, result.commands, strict=True)
    ]
    verdict, summary = _report_summary(result, outcomes)
    return {
        "commands": [
            _command_report(spec, item)
            for spec, item in zip(commands, result.commands, strict=True)
        ],
        "relabels": [
            {
                "path": relabel.path,
                "fromOperation": relabel.from_operation,
                "toOperation": relabel.to_operation,
            }
            for relabel in result.relabels
        ],
        "verdict": verdict,
        "summary": summary,
    }


def _is_pytest_command(argv: tuple[str, ...]) -> bool:
    """True for the argv shapes that run pytest itself.

    Only pytest has a dedicated "nothing was collected" exit code
    (5); recognising its invocations — the bare ``pytest`` entry
    point or ``python -m pytest`` under python/python3/py, with
    either path separator and an optional ``.exe`` suffix — is what
    keeps every other tool's exit 5 an ordinary failure.
    """
    if not argv:
        return False
    exe = argv[0].replace("\\", "/").rsplit("/", 1)[-1].lower()
    if exe.endswith(".exe"):
        exe = exe[: -len(".exe")]
    if exe == "pytest":
        return True
    return exe in ("python", "python3", "py") and list(argv[1:3]) == ["-m", "pytest"]


def _command_outcome(spec: CommandSpec, item: CommandResult) -> str:
    """One executed command's outcome: PASS, NO_TESTS or FAIL.

    NO_TESTS is pytest exit code 5 — the command ran fine and
    collected nothing, so there is no failure for a Fix agent to
    repair. The command's real exit code stays in the report.
    """
    if item.skipped:
        return "SKIPPED"
    if item.exit_code == 0:
        return "PASS"
    if item.exit_code == PYTEST_NO_TESTS_EXIT_CODE and _is_pytest_command(spec.argv):
        return "NO_TESTS"
    return "FAIL"


def _report_summary(result: SandboxResult, outcomes: list[str]) -> tuple[str, str]:
    executed = [
        outcome for item, outcome in zip(result.commands, outcomes, strict=True) if not item.skipped
    ]
    skipped_count = len(result.commands) - len(executed)
    passed = executed.count("PASS")
    if "FAIL" in executed:
        verdict = "FAIL"
    elif "NO_TESTS" in executed:
        verdict = "NO_TESTS"
    else:
        verdict = "PASS"
    summary = f"{verdict}: {passed}/{len(executed)} commands passed"
    if skipped_count:
        summary += f" ({skipped_count} skipped)"
    return verdict, summary


def _command_report(spec: CommandSpec, item: CommandResult) -> dict[str, Any]:
    argv = [_redact(arg) for arg in spec.argv]
    if item.skipped:
        return {
            "argv": argv,
            "exitCode": None,
            "stdout": "",
            "stderr": "",
            "durationMs": 0,
            "skipped": True,
        }
    return {
        "argv": argv,
        "exitCode": item.exit_code,
        "stdout": _output(item.stdout, spec.output_limit_bytes),
        "stderr": _output(item.stderr, spec.output_limit_bytes),
        "durationMs": item.duration_ms,
    }
