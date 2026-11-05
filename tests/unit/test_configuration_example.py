import shutil
import tempfile
import unittest
from pathlib import Path

from asf.configuration.loader import load_platform_config

EXAMPLE_PATH = Path(__file__).resolve().parents[2] / "config" / "platform.example.yaml"


class ConfigurationExampleTests(unittest.TestCase):
    def test_load_example_platform_config_successfully(self):
        self.assertTrue(EXAMPLE_PATH.is_file(), f"Missing example file at {EXAMPLE_PATH}")

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_platform_yaml = Path(tmp_dir) / "platform.yaml"
            shutil.copyfile(EXAMPLE_PATH, tmp_platform_yaml)

            config = load_platform_config(tmp_dir)
            self.assertEqual(config.version, 1)
            self.assertEqual(config.log_level, "INFO")
            # The example's retry policy names real gateway codes
            # (it once shipped TIMEOUT / RATE_LIMITED, which matched
            # nothing and silently disabled retries).
            spec_retry = config.agents["spec"].retry_policy
            self.assertIsNotNone(spec_retry)
            assert spec_retry is not None
            self.assertEqual(spec_retry.retry_on, ["LLM_TIMEOUT", "LLM_RATE_LIMITED"])
            self.assertEqual(config.paths.artifacts_dir, "artifacts")
            self.assertEqual(config.models.default, "fast")
            self.assertIn("fast", config.models.profiles)

            profile = config.models.profiles["fast"]
            self.assertEqual(profile.provider, "example-provider")
            self.assertEqual(profile.model, "example-fast-v1")
            self.assertIsNotNone(profile.credentials)
            assert profile.credentials is not None
            self.assertEqual(profile.credentials.env, "EXAMPLE_MODEL_API_KEY")

            # SourceControl and CI
            self.assertIsNotNone(config.source_control)
            assert config.source_control is not None
            self.assertEqual(config.source_control.provider, "example-provider")

            self.assertIsNotNone(config.ci)
            assert config.ci is not None
            self.assertEqual(config.ci.provider, "example-provider")

            # Notifications
            self.assertEqual(len(config.notifications), 1)
            self.assertEqual(config.notifications[0].name, "engineering-team")

            # Agent override
            self.assertIn("spec", config.agents)
            self.assertEqual(config.agents["spec"].model_profile, "fast")


if __name__ == "__main__":
    unittest.main()
