import tempfile
import unittest
from pathlib import Path

from asf.configuration.errors import ConfigError
from asf.configuration.loader import load_platform_config
from asf.configuration.yamlio import deep_merge, load_yaml_mapping


class ConfigurationLoadingTests(unittest.TestCase):
    def test_defaults_only_valid(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Empty directory with no platform.yaml
            config = load_platform_config(tmp_dir)
            self.assertEqual(config.version, 1)
            self.assertEqual(config.log_level, "INFO")
            self.assertEqual(config.paths.artifacts_dir, "artifacts")
            self.assertIsNone(config.models.default)
            self.assertEqual(config.models.profiles, {})
            self.assertEqual(config.notifications, [])
            self.assertEqual(config.agents, {})

    def test_precedence_and_deep_merge(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            base_yaml = tmp_path / "platform.yaml"
            local_yaml = tmp_path / "platform.local.yaml"

            base_yaml.write_text(
                """
version: 1
logLevel: INFO
models:
  default: fast
  profiles:
    fast:
      provider: prov-1
      model: model-1
      timeoutSeconds: 30
      parameters:
        temp: 0.5
        topP: 0.9
notifications:
  - name: team-a
    type: webhook
""",
                encoding="utf-8",
            )

            local_yaml.write_text(
                """
logLevel: DEBUG
models:
  profiles:
    fast:
      timeoutSeconds: 60
      parameters:
        temp: 0.8
notifications:
  - name: team-b
    type: webhook
""",
                encoding="utf-8",
            )

            config = load_platform_config(tmp_path)
            self.assertEqual(config.log_level, "DEBUG")
            profile = config.models.profiles["fast"]
            self.assertEqual(profile.timeout_seconds, 60)
            self.assertEqual(profile.parameters["temp"], 0.8)
            self.assertEqual(profile.parameters["topP"], 0.9)
            # List replaced by higher layer
            self.assertEqual(len(config.notifications), 1)
            self.assertEqual(config.notifications[0].name, "team-b")

    def test_config_dir_resolution_c3(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            (tmp_path / "platform.yaml").write_text("logLevel: WARNING\n", encoding="utf-8")

            # 1. Explicit argument
            cfg1 = load_platform_config(tmp_path)
            self.assertEqual(cfg1.log_level, "WARNING")

            # 2. ASF_CONFIG_DIR via injected environ
            cfg2 = load_platform_config(environ={"ASF_CONFIG_DIR": str(tmp_path)})
            self.assertEqual(cfg2.log_level, "WARNING")

            # 3. Missing explicit directory raises ConfigError
            missing_dir = tmp_path / "non_existent"
            with self.assertRaises(ConfigError):
                load_platform_config(missing_dir)

            # 4. Missing ASF_CONFIG_DIR raises ConfigError
            with self.assertRaises(ConfigError):
                load_platform_config(environ={"ASF_CONFIG_DIR": str(missing_dir)})

            # 5. Missing default ./config directory -> returns defaults only
            empty_environ = {"ASF_CONFIG_DIR": ""}
            # Provide non-existent default by running in tmp_dir
            defaults_cfg = load_platform_config(environ=empty_environ)
            self.assertEqual(defaults_cfg.log_level, "INFO")

    def test_duplicate_keys_rejected(self):
        yaml_content = """
logLevel: INFO
logLevel: DEBUG
"""
        with self.assertRaises(ConfigError) as ctx:
            load_yaml_mapping(yaml_content)
        self.assertTrue(len(ctx.exception.issues) > 0)

    def test_non_mapping_root_rejected(self):
        with self.assertRaises(ConfigError) as ctx:
            load_yaml_mapping("- item 1\n- item 2\n")
        self.assertIn("root must be a mapping", str(ctx.exception).lower())

    def test_empty_file_is_empty_mapping(self):
        data = load_yaml_mapping("")
        self.assertEqual(data, {})

        data_comment = load_yaml_mapping("# just a comment\n")
        self.assertEqual(data_comment, {})

    def test_deep_merge_utility(self):
        base = {"a": 1, "b": {"c": 2, "d": [1, 2]}}
        override = {"b": {"c": 3, "d": [3]}, "e": 4}
        merged = deep_merge(base, override)
        self.assertEqual(merged["a"], 1)
        self.assertEqual(merged["b"]["c"], 3)
        self.assertEqual(merged["b"]["d"], [3])
        self.assertEqual(merged["e"], 4)


if __name__ == "__main__":
    unittest.main()
