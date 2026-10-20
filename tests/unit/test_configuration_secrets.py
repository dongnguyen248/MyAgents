import json
import tempfile
import unittest
from pathlib import Path

from asf.configuration.errors import ConfigError
from asf.configuration.loader import load_platform_config
from asf.configuration.secrets import SecretRef


class ConfigurationSecretsTests(unittest.TestCase):
    def load_with_content(self, content: str):
        with tempfile.TemporaryDirectory() as tmp_dir:
            p = Path(tmp_dir) / "platform.yaml"
            p.write_text(content, encoding="utf-8")
            return load_platform_config(tmp_dir)

    def test_secret_ref_resolve_and_validation(self):
        ref = SecretRef(env="MY_API_KEY")
        self.assertEqual(ref.resolve({"MY_API_KEY": "secret-value-123"}), "secret-value-123")

        # Unset raises ConfigError
        with self.assertRaises(ConfigError) as ctx:
            ref.resolve({})
        self.assertIn("not set", str(ctx.exception))

        # Empty raises ConfigError
        with self.assertRaises(ConfigError) as ctx:
            ref.resolve({"MY_API_KEY": ""})
        self.assertIn("empty", str(ctx.exception))

    def test_secret_ref_repr_and_str_masking(self):
        sentinel = "SUPER_SECRET_VALUE_XYZ"
        ref = SecretRef(env="TARGET_ENV_VAR")
        resolved = ref.resolve({"TARGET_ENV_VAR": sentinel})
        self.assertEqual(resolved, sentinel)

        # Sentinel must be absent from repr and str
        self.assertNotIn(sentinel, repr(ref))
        self.assertNotIn(sentinel, str(ref))
        self.assertIn("TARGET_ENV_VAR", repr(ref))
        self.assertIn("TARGET_ENV_VAR", str(ref))

    def test_secret_ref_in_loaded_config_json_dump(self):
        sentinel = "SUPER_SECRET_TOKEN_ABC"
        content = """
models:
  profiles:
    fast:
      provider: example
      model: model-1
      credentials:
        env: PROVIDER_TOKEN
"""
        config = self.load_with_content(content)
        cred = config.models.profiles["fast"].credentials
        self.assertIsNotNone(cred)
        assert cred is not None
        resolved = cred.resolve({"PROVIDER_TOKEN": sentinel})
        self.assertEqual(resolved, sentinel)

        # JSON dump must contain env var name, never the resolved value
        dump_dict = config.model_dump(mode="json")
        dump_str = json.dumps(dump_dict)
        self.assertNotIn(sentinel, dump_str)
        self.assertNotIn(sentinel, repr(config))
        self.assertNotIn(sentinel, str(config))
        self.assertIn("PROVIDER_TOKEN", dump_str)

    def test_literal_secret_rejected_at_top_level_and_nested(self):
        # Literal in credentials
        content_credentials = """
models:
  profiles:
    fast:
      provider: example
      model: model-1
      credentials: "literal_api_key_value"
"""
        with self.assertRaises(ConfigError) as ctx:
            self.load_with_content(content_credentials)
        self.assertTrue(any("credentials" in iss.path for iss in ctx.exception.issues))

        # Literal in parameters (e.g. apiKey)
        content_params = """
models:
  profiles:
    fast:
      provider: example
      model: model-1
      parameters:
        apiKey: "raw_secret_key"
"""
        with self.assertRaises(ConfigError) as ctx:
            self.load_with_content(content_params)
        self.assertTrue(any("apiKey" in iss.path for iss in ctx.exception.issues))

        # Literal in settings
        content_settings = """
sourceControl:
  provider: git
  settings:
    token: "plain_text_token"
"""
        with self.assertRaises(ConfigError) as ctx:
            self.load_with_content(content_settings)
        self.assertTrue(any("token" in iss.path for iss in ctx.exception.issues))

    def test_null_secret_and_env_ref_accepted(self):
        content = """
models:
  profiles:
    fast:
      provider: example
      model: model-1
      credentials: null
      parameters:
        secretKey: null
        accessToken:
          env: VALID_ENV_TOKEN
"""
        config = self.load_with_content(content)
        fast = config.models.profiles["fast"]
        self.assertIsNone(fast.credentials)
        self.assertIsNone(fast.parameters["secretKey"])
        self.assertEqual(fast.parameters["accessToken"], {"env": "VALID_ENV_TOKEN"})

    def test_max_tokens_accepted(self):
        content = """
models:
  profiles:
    fast:
      provider: example
      model: model-1
      parameters:
        max_tokens: 1024
        maxTokens: 2048
"""
        config = self.load_with_content(content)
        params = config.models.profiles["fast"].parameters
        self.assertEqual(params["max_tokens"], 1024)
        self.assertEqual(params["maxTokens"], 2048)


if __name__ == "__main__":
    unittest.main()
