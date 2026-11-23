from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from asf.contracts.map_events import MapEvent, clean_label, host_label, path_label, shell_label

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "contracts" / "schemas" / "map-event.schema.json"
TS = datetime(2026, 11, 23, 9, 0, 0, tzinfo=UTC)


def make_event(**overrides: Any) -> MapEvent:
    fields: dict[str, Any] = {
        "id": "evt-1",
        "ts": TS,
        "run_id": "run-1",
        "span_id": "span-1",
        "type": "model",
        "station": "model",
        "phase": "start",
        "status": "running",
        "label": "fake-model",
    }
    fields.update(overrides)
    return MapEvent.model_validate(fields)


class MapEventSchemaTests(unittest.TestCase):
    def test_contract_dump_uses_camel_case(self) -> None:
        dumped = make_event(agent_id="agent-plan", duration_ms=42).to_contract()
        self.assertEqual(dumped["runId"], "run-1")
        self.assertEqual(dumped["spanId"], "span-1")
        self.assertEqual(dumped["agentId"], "agent-plan")
        self.assertEqual(dumped["durationMs"], 42)

    def test_unknown_station_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            make_event(station="browser")

    def test_overlong_label_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            make_event(label="x" * 121)

    def test_schema_file_matches_the_model(self) -> None:
        on_disk = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(on_disk, MapEvent.model_json_schema(by_alias=True))


class LabelTests(unittest.TestCase):
    def test_shell_label_keeps_only_the_command_name(self) -> None:
        self.assertEqual(shell_label("git push origin master"), "git")
        self.assertEqual(shell_label("/usr/bin/python -m pytest -q"), "python")
        self.assertEqual(shell_label("npm install --save left-pad"), "npm")
        self.assertEqual(shell_label(""), "")

    def test_host_label_keeps_only_the_host(self) -> None:
        url = "https://user:secret@gitlab.local:8443/group/proj.git?token=abc"
        self.assertEqual(host_label(url), "gitlab.local")
        self.assertEqual(host_label("https://api.github.com/repos/x"), "api.github.com")

    def test_clean_label_strips_controls_and_zero_width(self) -> None:
        self.assertEqual(clean_label("a\u200bb\tc\nd"), "a b c d")
        self.assertEqual(clean_label("  spaced   out  "), "spaced out")

    def test_clean_label_truncates_with_ellipsis(self) -> None:
        cleaned = clean_label("x" * 200)
        self.assertEqual(len(cleaned), 120)
        self.assertTrue(cleaned.endswith("…"))

    def test_path_label_keeps_only_the_last_two_levels(self) -> None:
        self.assertEqual(path_label("src/asf/api/demo.py"), "api/demo.py")
        self.assertEqual(path_label("demo.py"), "demo.py")
        self.assertEqual(path_label(""), "")

    def test_path_label_hides_windows_roots_and_home(self) -> None:
        label = path_label(r"E:\develops\JAVA\MyAgents\src\asf\api\demo.py")
        self.assertEqual(label, "api/demo.py")
        label = path_label("/home/dong/projects/secret-repo/passwords.txt")
        self.assertEqual(label, "secret-repo/passwords.txt")
        self.assertNotIn("dong", label)
        self.assertNotIn("home", label)


if __name__ == "__main__":
    unittest.main()
