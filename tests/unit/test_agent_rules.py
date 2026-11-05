from __future__ import annotations

import ast
import unittest
from pathlib import Path

from tests.unit.purity import assert_pure_package

REPO_ROOT = Path(__file__).resolve().parents[2]


class AgentRulesTests(unittest.TestCase):
    def test_purity_guards(self):
        # 1. Purity guard over all of src/asf/agents
        agents_dir = REPO_ROOT / "src" / "asf" / "agents"
        assert_pure_package(self, agents_dir)

        # 2. Purity guard over all of src/asf/contracts
        contracts_dir = REPO_ROOT / "src" / "asf" / "contracts"
        assert_pure_package(self, contracts_dir)

        # 3. Purity guard over src/asf/models (ports, errors, fake)
        models_dir = REPO_ROOT / "src" / "asf" / "models"
        assert_pure_package(self, models_dir, include=["ports.py", "errors.py", "fake.py"])

        # 4. Purity guard over src/asf/approval
        approval_dir = REPO_ROOT / "src" / "asf" / "approval"
        assert_pure_package(self, approval_dir)

        # 5. Purity guard over src/asf/state_machine
        sm_dir = REPO_ROOT / "src" / "asf" / "state_machine"
        assert_pure_package(self, sm_dir)

    def test_agent_logic_modules_import_boundaries(self):
        """Logic modules (base.py, spec/agent.py, spec/prompts.py) may import only
        asf.contracts, asf.models.ports, asf.models.errors, asf.agents.* and stdlib/pydantic.
        They must not import pathlib, importlib, os, shutil, tempfile.
        The shared rules helper (asf.agents._shared.rules) is allowlisted:
        it is pure (json/typing only) and carries the standing project
        rules into agent system prompts. The routing helper
        (asf.agents._shared.routing) is allowlisted on the same terms:
        pure (typing only), it carries the run's model tier into agent
        model-request metadata. The skills helper
        (asf.agents._shared.skills) is allowlisted on the same terms:
        pure (json/typing only), it carries the project's enabled
        skill bodies into agent system prompts. The model-errors
        helper (asf.agents._shared.model_errors) is allowlisted on
        the same terms: it builds the one standard invalid-response
        error every agent reports for an unusable model reply. The
        model-call helper (asf.agents._shared.model_call) is
        allowlisted on the same terms: it is the one place that
        interprets a model response's finish_reason (truncation,
        provider blocks) for every agent. The counting gateway
        (asf.models.counting) is allowlisted: BaseAgent wraps every
        agent's gateway in it so usage accounting and step-deadline
        injection are platform concerns, not agent bookkeeping.
        """
        agents_dir = REPO_ROOT / "src" / "asf" / "agents"
        logic_modules = [
            agents_dir / "base.py",
            agents_dir / "spec" / "agent.py",
            agents_dir / "spec" / "prompts.py",
        ]

        forbidden_stdlib = {"pathlib", "importlib", "os", "shutil", "tempfile"}
        allowed_asf_modules = {
            "asf.contracts",
            "asf.contracts.models",
            "asf.models.ports",
            "asf.models.errors",
            "asf.agents",
            "asf.agents.base",
            "asf.agents._shared.rules",
            "asf.agents._shared.routing",
            "asf.agents._shared.skills",
            "asf.agents._shared.model_errors",
            "asf.agents._shared.model_call",
            "asf.models.counting",
            "asf.agents.spec",
            "asf.agents.spec.agent",
            "asf.agents.spec.prompts",
        }

        for py_file in logic_modules:
            self.assertTrue(py_file.exists(), f"File {py_file} does not exist")
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        for bad in forbidden_stdlib:
                            self.assertFalse(
                                alias.name == bad or alias.name.startswith(f"{bad}."),
                                f"Forbidden stdlib import '{alias.name}' in {py_file.name}",
                            )
                        if alias.name.startswith("asf."):
                            self.assertIn(
                                alias.name,
                                allowed_asf_modules,
                                f"Disallowed asf import '{alias.name}' in {py_file.name}",
                            )
                elif isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    for bad in forbidden_stdlib:
                        self.assertFalse(
                            mod == bad or mod.startswith(f"{bad}."),
                            f"Forbidden stdlib import from '{mod}' in {py_file.name}",
                        )
                    if node.level == 0 and mod.startswith("asf."):
                        self.assertIn(
                            mod,
                            allowed_asf_modules,
                            f"Disallowed asf import from '{mod}' in {py_file.name}",
                        )

    def test_nothing_under_agents_imports_forbidden_packages(self):
        """Nothing under asf.agents may import asf.approval, asf.state_machine,
        asf.workflow, asf.storage, asf.integrations, asf.models.providers,
        asf.models.fake, asf.orchestrator.
        """
        agents_dir = REPO_ROOT / "src" / "asf" / "agents"
        forbidden = [
            "asf.approval",
            "asf.state_machine",
            "asf.workflow",
            "asf.storage",
            "asf.integrations",
            "asf.models.providers",
            "asf.models.fake",
            "asf.orchestrator",
        ]

        assert_pure_package(self, agents_dir, forbidden_modules=forbidden)

    def test_contracts_import_boundaries(self):
        """asf.contracts must not import asf.agents, asf.models, asf.workflow,
        asf.state_machine, asf.storage, asf.integrations, asf.orchestrator.
        """
        contracts_dir = REPO_ROOT / "src" / "asf" / "contracts"
        forbidden = [
            "asf.agents",
            "asf.models",
            "asf.workflow",
            "asf.state_machine",
            "asf.storage",
            "asf.integrations",
            "asf.orchestrator",
        ]
        assert_pure_package(self, contracts_dir, forbidden_modules=forbidden)

    def test_models_import_boundaries(self):
        """asf.models must import only asf.contracts (and itself)."""
        models_dir = REPO_ROOT / "src" / "asf" / "models"
        forbidden = [
            "asf.agents",
            "asf.approval",
            "asf.configuration",
            "asf.workflow",
            "asf.state_machine",
            "asf.storage",
            "asf.integrations",
            "asf.orchestrator",
        ]
        assert_pure_package(self, models_dir, forbidden_modules=forbidden)
