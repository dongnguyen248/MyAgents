import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from asf.configuration.errors import ConfigError, ConfigIssue

SCHEMA_PATH = (
    Path(__file__).resolve().parents[2] / "contracts" / "schemas" / "contracts.schema.json"
)
with SCHEMA_PATH.open(encoding="utf-8") as f:
    SCHEMA = json.load(f)


def platform_error_validator():
    wrapped_schema = {
        "$schema": SCHEMA["$schema"],
        "$defs": SCHEMA["$defs"],
        "$ref": "#/$defs/PlatformError",
    }
    return Draft202012Validator(wrapped_schema, format_checker=FormatChecker())


class ConfigurationErrorsTests(unittest.TestCase):
    def test_to_platform_errors_validates_against_contract(self):
        issue1 = ConfigIssue(path="models.profiles.fast.timeoutSeconds", message="must be > 0")
        issue2 = ConfigIssue(path="notifications[0].name", message="name is required")
        err = ConfigError(
            issues=[issue1, issue2],
            source="config/platform.yaml",
        )

        fixed_time = datetime(2026, 10, 20, 14, 0, 0, tzinfo=timezone.utc)
        platform_errors = err.to_platform_errors(now=fixed_time)

        self.assertEqual(len(platform_errors), 2)
        validator = platform_error_validator()

        for pe in platform_errors:
            with self.subTest(error_msg=pe["message"]):
                validator.validate(pe)
                self.assertEqual(pe["code"], "VALIDATION_FAILED")
                self.assertEqual(pe["category"], "VALIDATION")
                self.assertFalse(pe["retryable"])
                self.assertEqual(pe["timestamp"], "2026-10-20T14:00:00+00:00")
                self.assertEqual(pe["details"]["source"], "config/platform.yaml")

        self.assertEqual(
            platform_errors[0]["message"],
            "models.profiles.fast.timeoutSeconds: must be > 0",
        )
        self.assertEqual(
            platform_errors[1]["message"],
            "notifications[0].name: name is required",
        )

    def test_to_platform_errors_without_issues(self):
        err = ConfigError("General configuration failure", source="settings.yaml")
        platform_errors = err.to_platform_errors()
        self.assertEqual(len(platform_errors), 1)

        pe = platform_errors[0]
        platform_error_validator().validate(pe)
        self.assertEqual(pe["code"], "VALIDATION_FAILED")
        self.assertEqual(pe["category"], "VALIDATION")
        self.assertFalse(pe["retryable"])
        self.assertEqual(pe["details"]["source"], "settings.yaml")


if __name__ == "__main__":
    unittest.main()
