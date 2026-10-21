import json
import os
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
            # Provide non-existent default by running in tmp_dir (which has no ./config)
            cwd_before = Path.cwd()
            try:
                os.chdir(tmp_dir)
                defaults_cfg = load_platform_config(environ=empty_environ)
                self.assertEqual(defaults_cfg.log_level, "INFO")
            finally:
                os.chdir(cwd_before)


    def test_duplicate_keys_rejected(self):
        yaml_content = """
logLevel: INFO
logLevel: DEBUG
"""
        with self.assertRaises(ConfigError) as ctx:
            load_yaml_mapping(yaml_content)
        self.assertTrue(len(ctx.exception.issues) > 0)

    def test_yaml_duplicate_key_never_embeds_source_snippets_or_secret_values(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "config.yaml"
            file_path.write_text("token: SENTINEL_A\ntoken: SENTINEL_A\n", encoding="utf-8")
            with self.assertRaises(ConfigError) as ctx:
                load_yaml_mapping(file_path)
            err = ctx.exception
            err_str = str(err)
            self.assertNotIn("SENTINEL_A", err_str)
            for issue in err.issues:
                self.assertNotIn("SENTINEL_A", issue.message)
            platform_errors_json = json.dumps(err.to_platform_errors())
            self.assertNotIn("SENTINEL_A", platform_errors_json)
            self.assertRegex(err_str, r"\bline 2\b")

    def test_yaml_syntax_error_never_embeds_source_snippets_or_secret_values(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "config.yaml"
            file_path.write_text("apiKey: SENTINEL_B: bad\n", encoding="utf-8")
            with self.assertRaises(ConfigError) as ctx:
                load_yaml_mapping(file_path)
            err = ctx.exception
            err_str = str(err)
            self.assertNotIn("SENTINEL_B", err_str)
            for issue in err.issues:
                self.assertNotIn("SENTINEL_B", issue.message)
            platform_errors_json = json.dumps(err.to_platform_errors())
            self.assertNotIn("SENTINEL_B", platform_errors_json)
            self.assertRegex(err_str, r"\bline 1\b")



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

    def test_deep_merge_purity_and_no_shared_nested_objects(self):
        base = {
            "scalar": 1,
            "nested": {"key": "base_val", "items": [1, 2]},
            "untouched": {"key": "original"},
        }
        override = {
            "scalar": 2,
            "nested": {"key": "override_val", "new_items": [3, 4]},
            "added": {"key": "new_val"},
        }
        base_copy = {
            "scalar": 1,
            "nested": {"key": "base_val", "items": [1, 2]},
            "untouched": {"key": "original"},
        }
        override_copy = {
            "scalar": 2,
            "nested": {"key": "override_val", "new_items": [3, 4]},
            "added": {"key": "new_val"},
        }

        merged = deep_merge(base, override)

        # 1. Inputs are not mutated during deep_merge
        self.assertEqual(base, base_copy)
        self.assertEqual(override, override_copy)

        # 2. Mutating merged must not affect base or override (no shared nested objects)
        merged["nested"]["key"] = "mutated"
        merged["nested"]["items"].append(999)
        merged["nested"]["new_items"].append(999)
        merged["untouched"]["key"] = "mutated"
        merged["added"]["key"] = "mutated"

        self.assertEqual(base, base_copy)
        self.assertEqual(override, override_copy)

        # 3. Mutating base or override afterwards must not affect merged
        base["untouched"]["key"] = "mutated_base"
        override["added"]["key"] = "mutated_override"
        self.assertEqual(merged["untouched"]["key"], "mutated")
        self.assertEqual(merged["added"]["key"], "mutated")

    def test_no_dead_aliases_or_duplicate_reexports(self):
        import asf.configuration.loader as config_loader
        import asf.workflow.definition as wf_definition

        self.assertFalse(
            hasattr(config_loader, "_validation_error_to_config_error"),
            "_validation_error_to_config_error dead alias should be removed",
        )
        self.assertNotIn(
            "validation_error_to_config_error",
            wf_definition.__all__,
            "validation_error_to_config_error should not be re-exported by asf.workflow.definition",
        )


if __name__ == "__main__":
    unittest.main()

