from __future__ import annotations

import json
import unittest
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from asf.contracts.map_events import MapEvent
from asf.contracts.models import AgentRequest
from asf.integrations.hosting.http import HttpResponse
from asf.integrations.hosting.ports import HostingError
from asf.models.map_tap import map_call_context, set_default_map_tap
from asf.tools.changeset import ChangeSet, FileChange
from asf.tools.map_wrap import MapRepository, MapSandbox, MapTransport
from asf.tools.ports import (
    CommandResult,
    CommandSpec,
    FileNotFoundInRepository,
    SandboxError,
    SandboxResult,
)

SECRET = "SECRET-VALUE-12345"
STARTED = datetime(2026, 11, 23, 9, 0, 0, tzinfo=UTC)


def make_request() -> AgentRequest:
    return AgentRequest(
        request_id="req-1",
        task_id="task-1",
        project_id="proj-1",
        workflow_id="software-development",
        agent_id="agent-test",
        input={},
        metadata={"runId": "run-1"},
    )


def changes() -> ChangeSet:
    return ChangeSet(changes=[FileChange(path="a.py", operation="create", content="x")])


class CollectingTap:
    def __init__(self) -> None:
        self.events: list[MapEvent] = []

    def emit(self, event: MapEvent) -> None:
        self.events.append(event)

    def dumped(self) -> str:
        return json.dumps([event.to_contract() for event in self.events])


class RaisingTap:
    def emit(self, event: MapEvent) -> None:
        raise RuntimeError("tap is broken")


class FakeRepository:
    def list_tree(self, ref: str, prefix: str = "") -> tuple[str, ...]:
        return ("src/a.py",)

    def read_file(self, path: str, ref: str, max_bytes: int = 256_000) -> str:
        if path.endswith("missing.py"):
            raise FileNotFoundInRepository(path, ref)
        return "content"


class FakeSandbox:
    def __init__(self, result: SandboxResult | None = None, error: Exception | None = None) -> None:
        self._result = result
        self._error = error

    def run(
        self,
        commands: Sequence[CommandSpec],
        changes_: ChangeSet,
        ref: str,
        *,
        fail_fast: bool = True,
    ) -> SandboxResult:
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result


class FakeTransport:
    def __init__(self, status: int = 200, error: Exception | None = None) -> None:
        self._status = status
        self._error = error

    def __call__(
        self, method: str, url: str, headers: Mapping[str, str], body: bytes | None
    ) -> HttpResponse:
        if self._error is not None:
            raise self._error
        return HttpResponse(status=self._status, body=b"{}")


class MapWrapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tap = CollectingTap()
        set_default_map_tap(self.tap)

    def tearDown(self) -> None:
        set_default_map_tap(None)

    def test_repository_pulses_carry_two_level_paths_only(self) -> None:
        repo = MapRepository(FakeRepository())
        with map_call_context(make_request(), STARTED):
            content = repo.read_file(r"E:\develops\secret-proj\src\TokenStore.cs", "main")
            tree = repo.list_tree("main", "src/asf/api")
        self.assertEqual(content, "content")
        self.assertEqual(tree, ("src/a.py",))
        labels = [event.label for event in self.tap.events]
        self.assertEqual(labels, ["src/TokenStore.cs", "src/TokenStore.cs", "asf/api", "asf/api"])
        self.assertNotIn("develops", self.tap.dumped())
        self.assertNotIn("secret-proj", self.tap.dumped())
        first = self.tap.events[0]
        self.assertEqual(first.station, "files")
        self.assertEqual(first.type, "tool")
        self.assertEqual(first.parent_id, "req-1")
        self.assertEqual(first.agent_id, "agent-test")

    def test_repository_error_pulses_and_propagates(self) -> None:
        repo = MapRepository(FakeRepository())
        with map_call_context(make_request(), STARTED), self.assertRaises(FileNotFoundInRepository):
            repo.read_file("src/missing.py", "main")
        end = self.tap.events[-1]
        self.assertEqual(end.status, "error")
        self.assertEqual(end.error_code, "FileNotFoundInRepository")

    def test_sandbox_pulses_use_command_names_never_arguments(self) -> None:
        result = SandboxResult(
            commands=(
                CommandResult(exit_code=0, stdout="", stderr="", duration_ms=120),
                CommandResult(exit_code=3, stdout="", stderr="", duration_ms=30),
                CommandResult(exit_code=-1, stdout="", stderr="", duration_ms=0, skipped=True),
            )
        )
        sandbox = MapSandbox(FakeSandbox(result=result))
        commands = [
            CommandSpec(argv=("python", "-m", "pytest", f"--api-key={SECRET}")),
            CommandSpec(argv=("npm", "test")),
            CommandSpec(argv=("dotnet", "test")),
        ]
        with map_call_context(make_request(), STARTED):
            outcome = sandbox.run(commands, changes(), "main")
        self.assertIs(outcome, result)
        starts = [e for e in self.tap.events if e.phase == "start"]
        ends = [e for e in self.tap.events if e.phase == "end"]
        self.assertEqual([e.label for e in starts], ["python", "npm", "dotnet"])
        self.assertEqual([e.status for e in ends], ["ok", "error", "blocked"])
        self.assertEqual(ends[1].error_code, "EXIT_3")
        self.assertEqual(ends[0].duration_ms, 120)
        self.assertNotIn(SECRET, self.tap.dumped())
        self.assertNotIn("api-key", self.tap.dumped())

    def test_sandbox_exception_ends_first_command_as_error(self) -> None:
        sandbox = MapSandbox(FakeSandbox(error=SandboxError("spawn failed")))
        commands = [CommandSpec(argv=("python", "-m", "pytest")), CommandSpec(argv=("npm", "test"))]
        with map_call_context(make_request(), STARTED), self.assertRaises(SandboxError):
            sandbox.run(commands, changes(), "main")
        ends = [e for e in self.tap.events if e.phase == "end"]
        self.assertEqual([e.status for e in ends], ["error", "blocked"])
        self.assertEqual(ends[0].error_code, "SandboxError")

    def test_transport_pulses_use_host_only(self) -> None:
        transport = MapTransport(FakeTransport())
        url = f"https://alice-wonderland:rabbit-hole-9@gitlab.local:8443/api/v4/x?token={SECRET}"
        with map_call_context(make_request(), STARTED):
            response = transport("GET", url, {"Authorization": f"Bearer {SECRET}"}, None)
        self.assertEqual(response.status, 200)
        self.assertEqual([e.label for e in self.tap.events], ["gitlab.local", "gitlab.local"])
        dumped = self.tap.dumped()
        for leaked in (SECRET, "alice-wonderland", "rabbit-hole-9", "token=", "Bearer"):
            self.assertNotIn(leaked, dumped)

    def test_transport_http_error_and_exception(self) -> None:
        transport = MapTransport(FakeTransport(status=502))
        with map_call_context(make_request(), STARTED):
            transport("POST", "https://api.github.com/x", {}, b"{}")
        self.assertEqual(self.tap.events[-1].error_code, "HTTP_502")
        failing = MapTransport(FakeTransport(error=HostingError("down", retryable=True)))
        with map_call_context(make_request(), STARTED), self.assertRaises(HostingError):
            failing("GET", "https://api.github.com/x", {}, None)
        self.assertEqual(self.tap.events[-1].error_code, "HostingError")

    def test_bound_run_attributes_without_an_agent_context(self) -> None:
        repo = MapRepository(
            FakeRepository(), bound_run=lambda: "run-9", bound_project=lambda: "proj-9"
        )
        repo.list_tree("main")
        self.assertEqual(len(self.tap.events), 2)
        self.assertEqual(self.tap.events[0].run_id, "run-9")
        self.assertEqual(self.tap.events[0].project_id, "proj-9")
        self.assertTrue(self.tap.events[0].span_id.startswith("run:run-9:tool:"))

    def test_no_context_and_no_binding_stays_silent(self) -> None:
        repo = MapRepository(FakeRepository())
        self.assertEqual(repo.read_file("src/a.py", "main"), "content")
        self.assertEqual(self.tap.events, [])

    def test_raising_tap_never_changes_results(self) -> None:
        set_default_map_tap(RaisingTap())
        repo = MapRepository(FakeRepository())
        transport = MapTransport(FakeTransport())
        with map_call_context(make_request(), STARTED):
            self.assertEqual(repo.read_file("src/a.py", "main"), "content")
            self.assertEqual(transport("GET", "https://api.github.com/x", {}, None).status, 200)


if __name__ == "__main__":
    unittest.main()
