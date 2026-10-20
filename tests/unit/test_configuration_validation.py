import tempfile
import unittest
from pathlib import Path

from asf.configuration.errors import ConfigError
from asf.configuration.loader import load_platform_config


class ConfigurationValidationTests(unittest.TestCase):
    def load_with_content(self, content: str):
        with tempfile.TemporaryDirectory() as tmp_dir:
            p = Path(tmp_dir) / "platform.yaml"
            p.write_text(content, encoding="utf-8")
            return load_platform_config(tmp_dir)

    def test_unknown_key_rejected_with_dotted_path(self):
        content = """
unknownKey: value
"""
        with self.assertRaises(ConfigError) as ctx:
            self.load_with_content(content)
        self.assertTrue(len(ctx.exception.issues) > 0)
        paths = [iss.path for iss in ctx.exception.issues]
        self.assertIn("unknownKey", paths)

    def test_nested_unknown_key_rejected_with_dotted_path(self):
        content = """
models:
  profiles:
    fast:
      provider: example
      model: model-1
      unknownField: bad
"""
        with self.assertRaises(ConfigError) as ctx:
            self.load_with_content(content)
        self.assertTrue(len(ctx.exception.issues) > 0)
        paths = [iss.path for iss in ctx.exception.issues]
        self.assertTrue(any("unknownField" in p for p in paths))

    def test_models_default_missing_profile(self):
        content = """
models:
  default: nonexistent
  profiles:
    fast:
      provider: example
      model: model-1
"""
        with self.assertRaises(ConfigError) as ctx:
            self.load_with_content(content)
        self.assertTrue(len(ctx.exception.issues) > 0)
        self.assertTrue(any("default" in iss.message.lower() for iss in ctx.exception.issues))

    def test_agent_model_profile_missing(self):
        content = """
models:
  profiles:
    fast:
      provider: example
      model: model-1
agents:
  spec:
    modelProfile: missing-profile
"""
        with self.assertRaises(ConfigError) as ctx:
            self.load_with_content(content)
        self.assertTrue(len(ctx.exception.issues) > 0)
        self.assertTrue(any("missing-profile" in iss.message for iss in ctx.exception.issues))

    def test_duplicate_notification_names_rejected(self):
        content = """
notifications:
  - name: team-slack
    type: webhook
  - name: team-slack
    type: email
"""
        with self.assertRaises(ConfigError) as ctx:
            self.load_with_content(content)
        self.assertTrue(len(ctx.exception.issues) > 0)
        self.assertTrue(any("unique" in iss.message.lower() for iss in ctx.exception.issues))

    def test_timeout_seconds_non_positive_rejected(self):
        content = """
models:
  profiles:
    fast:
      provider: example
      model: model-1
      timeoutSeconds: 0
"""
        with self.assertRaises(ConfigError) as ctx:
            self.load_with_content(content)
        self.assertTrue(len(ctx.exception.issues) > 0)
        paths = [iss.path for iss in ctx.exception.issues]
        self.assertTrue(any("timeoutSeconds" in p for p in paths))

    def test_version_not_one_rejected(self):
        content = """
version: 2
"""
        with self.assertRaises(ConfigError) as ctx:
            self.load_with_content(content)
        self.assertTrue(len(ctx.exception.issues) > 0)
        paths = [iss.path for iss in ctx.exception.issues]
        self.assertIn("version", paths)

    def test_invalid_log_level_rejected(self):
        content = """
logLevel: VERBOSE
"""
        with self.assertRaises(ConfigError) as ctx:
            self.load_with_content(content)
        self.assertTrue(len(ctx.exception.issues) > 0)
        paths = [iss.path for iss in ctx.exception.issues]
        self.assertIn("logLevel", paths)


if __name__ == "__main__":
    unittest.main()
