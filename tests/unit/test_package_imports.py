"""Test package imports and version definition."""

import importlib
import pkgutil
import unittest

import asf


class PackageImportsTest(unittest.TestCase):
    def test_import_asf_and_version(self) -> None:
        self.assertTrue(hasattr(asf, "__version__"))
        self.assertIsInstance(asf.__version__, str)
        self.assertGreater(len(asf.__version__), 0)

    def test_expected_subpackages_exist(self) -> None:
        expected_subpackages = [
            "orchestrator",
            "workflow",
            "state_machine",
            "approval",
            "evaluation",
            "configuration",
            "agents",
            "integrations",
            "models",
            "contracts",
            "tools",
            "execution",
            "storage",
            "api",
            "cli",
        ]
        for name in expected_subpackages:
            module_name = f"asf.{name}"
            mod = importlib.import_module(module_name)
            self.assertIsNotNone(mod, f"Failed to import {module_name}")

    def test_all_walk_packages_import(self) -> None:
        imported_count = 0
        for module_info in pkgutil.walk_packages(asf.__path__, "asf."):
            mod = importlib.import_module(module_info.name)
            self.assertIsNotNone(mod)
            imported_count += 1
        self.assertGreater(imported_count, 0)


if __name__ == "__main__":
    unittest.main()
