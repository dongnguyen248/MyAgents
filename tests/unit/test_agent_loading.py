from __future__ import annotations

import fnmatch
import tempfile
import tomllib
import unittest
from pathlib import Path

from asf.agents.base import AgentRuntime
from asf.agents.loading import load_spec_prompts, load_spec_template
from asf.agents.spec.factory import build_spec_agent
from asf.agents.spec.prompts import SpecTemplate
from asf.configuration.errors import ConfigError
from asf.configuration.platform import (
    AgentSettings,
    ModelProfile,
    ModelsConfig,
    PlatformConfig,
)
from asf.models.fake import ScriptedModelGateway

REPO_ROOT = Path(__file__).resolve().parents[2]


class AgentLoadingTests(unittest.TestCase):
    def test_load_spec_prompts_from_package(self):
        prompts = load_spec_prompts()
        self.assertTrue(prompts.system.strip())
        self.assertTrue(prompts.revision.strip())
        self.assertIn("senior business analyst", prompts.system)
        self.assertIn("reviewer feedback", prompts.revision)

    def test_load_spec_template_from_repo(self):
        templates_dir = REPO_ROOT / "templates"
        template = load_spec_template(templates_dir)
        self.assertTrue(template.text.strip())
        self.assertEqual(
            template.required_sections,
            [
                "## Background / Goal",
                "## Scope (in / out)",
                "## Functional requirements",
                "## Non-functional requirements",
                "## Acceptance criteria",
                "## Open questions",
                "## Revision history",
            ],
        )

    def test_spec_template_from_text(self):
        sample_text = (
            "# My Spec\n"
            "## Section One\n"
            "content 1\n"
            "## Section Two\n"
            "content 2\n"
            "### Subsection\n"
            "content 3\n"
        )
        tpl = SpecTemplate.from_text(sample_text)
        self.assertEqual(tpl.required_sections, ["## Section One", "## Section Two"])

    def test_missing_template_raises_config_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_dir = Path(tmpdir) / "nonexistent"
            with self.assertRaises(ConfigError) as ctx:
                load_spec_template(bad_dir)
            expected_path = str(bad_dir / "spec" / "SPEC.md")
            self.assertIn(expected_path, str(ctx.exception))
            self.assertEqual(ctx.exception.source, expected_path)

    def test_build_spec_agent_with_and_without_profile(self):
        runtime = AgentRuntime(
            models=ScriptedModelGateway([]),
            clock=lambda: unittest.mock.MagicMock(),  # type: ignore[return-value]
            new_id=lambda: "id-1",
        )
        templates_dir = REPO_ROOT / "templates"

        # Case 1: with model profile
        profile = ModelProfile(
            provider="test-prov",
            model="gpt-4o-mini",
            parameters={"temperature": 0.2},
        )
        platform_with_profile = PlatformConfig(
            models=ModelsConfig(profiles={"spec-model": profile}),
            agents={"spec": AgentSettings(model_profile="spec-model")},
        )
        agent_with = build_spec_agent(runtime, platform_with_profile, templates_dir)
        self.assertEqual(agent_with._model, "gpt-4o-mini")
        self.assertEqual(agent_with._parameters, {"temperature": 0.2})

        # Case 2: without model profile / empty agent settings
        platform_empty = PlatformConfig(
            models=ModelsConfig(profiles={}),
            agents={"spec": AgentSettings(model_profile=None)},
        )
        agent_without = build_spec_agent(runtime, platform_empty, templates_dir)
        self.assertIsNone(agent_without._model)
        self.assertEqual(agent_without._parameters, {})

    def test_prompt_md_files_matched_by_package_data_glob(self):
        pyproject_path = REPO_ROOT / "pyproject.toml"
        pyproject_data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        globs = pyproject_data["tool"]["setuptools"]["package-data"]["asf"]

        prompts_dir = REPO_ROOT / "src" / "asf" / "agents" / "spec" / "prompts"
        md_files = list(prompts_dir.glob("*.md"))
        self.assertTrue(len(md_files) >= 2)

        for md_file in md_files:
            rel_to_asf = md_file.relative_to(REPO_ROOT / "src" / "asf").as_posix()
            matched = any(fnmatch.fnmatch(rel_to_asf, pattern) for pattern in globs)
            self.assertTrue(
                matched,
                f"File '{rel_to_asf}' is not matched by package-data globs {globs}",
            )
