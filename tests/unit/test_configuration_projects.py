import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from asf.configuration.errors import ConfigError
from asf.configuration.loader import load_project, load_projects

SCHEMA_PATH = (
    Path(__file__).resolve().parents[2] / "contracts" / "schemas" / "contracts.schema.json"
)
with SCHEMA_PATH.open(encoding="utf-8") as f:
    SCHEMA = json.load(f)

PROJECTS_DIR = Path(__file__).resolve().parents[2] / "projects"


def project_validator():
    wrapped_schema = {
        "$schema": SCHEMA["$schema"],
        "$defs": SCHEMA["$defs"],
        "$ref": "#/$defs/Project",
    }
    return Draft202012Validator(wrapped_schema, format_checker=FormatChecker())


class ConfigurationProjectsTests(unittest.TestCase):
    def test_load_real_projects_and_validate_contracts(self):
        projects = load_projects(PROJECTS_DIR)
        self.assertGreaterEqual(len(projects), 2)
        self.assertIn("vhpc", projects)
        self.assertIn("vnpc", projects)

        validator = project_validator()
        for project_id, profile in projects.items():
            with self.subTest(project_id=project_id):
                contract_dict = profile.to_contract()
                validator.validate(contract_dict)
                self.assertEqual(contract_dict["id"], project_id)
                self.assertEqual(contract_dict["status"], "ACTIVE")

    def test_defaults_applied_when_keys_absent(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "sample_app.yaml"
            file_path.write_text(
                """
name: Sample Application
repository:
  provider: git
technology:
  backend: [python]
workflow: software-development
""",
                encoding="utf-8",
            )
            profile = load_project(file_path)
            self.assertEqual(profile.id, "sample_app")  # from stem
            self.assertEqual(profile.description, "")
            self.assertEqual(profile.enabled_agents, [])
            self.assertEqual(profile.enabled_skills, [])
            self.assertEqual(profile.configuration, {})
            self.assertEqual(profile.status, "ACTIVE")

            # Contract output is valid
            contract_dict = profile.to_contract()
            project_validator().validate(contract_dict)

    def test_id_stem_mismatch_raises_config_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "my_project.yaml"
            file_path.write_text(
                """
id: different_id
name: Mismatch App
repository:
  provider: git
technology:
  backend: [python]
workflow: software-development
""",
                encoding="utf-8",
            )
            with self.assertRaises(ConfigError) as ctx:
                load_project(file_path)
            self.assertTrue(any("id" in iss.path for iss in ctx.exception.issues))
            self.assertIn("does not match file stem", str(ctx.exception))

    def test_duplicate_project_ids_raises_config_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            (tmp_path / "app1.yaml").write_text(
                """
id: app1
name: App 1
repository:
  provider: git
technology:
  backend: [python]
workflow: software-development
""",
                encoding="utf-8",
            )
            # Second file with same id (explicit id matching, but different file or extension)
            # Or app1.yml with same stem
            (tmp_path / "app1.yml").write_text(
                """
id: app1
name: App 1 Duplicate
repository:
  provider: git
technology:
  backend: [python]
workflow: software-development
""",
                encoding="utf-8",
            )
            with self.assertRaises(ConfigError) as ctx:
                load_projects(tmp_path)
            self.assertTrue(any("duplicate" in iss.message.lower() for iss in ctx.exception.issues))

    def test_bad_status_rejected(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "app.yaml"
            file_path.write_text(
                """
name: App
repository:
  provider: git
technology:
  backend: [python]
workflow: software-development
status: UNKNOWN_STATUS
""",
                encoding="utf-8",
            )
            with self.assertRaises(ConfigError) as ctx:
                load_project(file_path)
            self.assertTrue(any("status" in iss.path for iss in ctx.exception.issues))

    def test_unknown_key_rejected(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "app.yaml"
            file_path.write_text(
                """
name: App
repository:
  provider: git
technology:
  backend: [python]
workflow: software-development
unexpectedField: "not allowed"
""",
                encoding="utf-8",
            )
            with self.assertRaises(ConfigError) as ctx:
                load_project(file_path)
            self.assertTrue(any("unexpectedField" in iss.path for iss in ctx.exception.issues))

    def test_literal_secret_under_repository_token_rejected(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "app.yaml"
            file_path.write_text(
                """
name: App
repository:
  provider: git
  token: "ghp_literal_secret_token_123"
technology:
  backend: [python]
workflow: software-development
""",
                encoding="utf-8",
            )
            with self.assertRaises(ConfigError) as ctx:
                load_project(file_path)
            self.assertTrue(any(iss.path == "repository.token" for iss in ctx.exception.issues))
            self.assertIn("must be null or {env: ENV_VAR}", str(ctx.exception))

    def test_literal_secret_under_configuration_api_key_rejected(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "app.yaml"
            file_path.write_text(
                """
name: App
repository:
  provider: git
technology:
  backend: [python]
workflow: software-development
configuration:
  apiKey: "secret_api_key_literal_value"
""",
                encoding="utf-8",
            )
            with self.assertRaises(ConfigError) as ctx:
                load_project(file_path)
            self.assertTrue(any(iss.path == "configuration.apiKey" for iss in ctx.exception.issues))
            self.assertIn("must be null or {env: ENV_VAR}", str(ctx.exception))

    def test_secret_scan_accepts_env_ref_and_null_in_repository_and_configuration(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "app.yaml"
            file_path.write_text(
                """
name: App
repository:
  provider: git
  token:
    env: GITHUB_TOKEN
technology:
  backend: [python]
workflow: software-development
configuration:
  apiKey:
    env: APP_API_KEY
  optionalSecret: null
""",
                encoding="utf-8",
            )
            profile = load_project(file_path)
            self.assertEqual(profile.repository["token"], {"env": "GITHUB_TOKEN"})
            self.assertEqual(profile.configuration["apiKey"], {"env": "APP_API_KEY"})
            self.assertIsNone(profile.configuration["optionalSecret"])
            contract_dict = profile.to_contract()
            project_validator().validate(contract_dict)


if __name__ == "__main__":
    unittest.main()
