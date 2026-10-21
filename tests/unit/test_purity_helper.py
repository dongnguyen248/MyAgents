from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.unit.purity import assert_pure_package


class PurityHelperTests(unittest.TestCase):
    def test_clean_file_passes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            clean_file = tmppath / "clean.py"
            clean_file.write_text(
                "x = 42\ndef add(a: int, b: int) -> int:\n    return a + b\n",
                encoding="utf-8",
            )

            # Should not raise
            assert_pure_package(self, tmppath)

    def test_nested_subpackage_file_with_import_os_is_caught(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            subpkg = tmppath / "sub" / "pkg"
            subpkg.mkdir(parents=True)
            dirty_file = subpkg / "bad.py"
            dirty_file.write_text(
                "import os\n\ndef get_pid() -> int:\n    return os.getpid()\n",
                encoding="utf-8",
            )

            with self.assertRaises(AssertionError):
                assert_pure_package(self, tmppath)

    def test_relative_import_of_forbidden_module_is_caught(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            src_dir = tmppath / "src"
            pkg_dir = src_dir / "asf" / "approval"
            pkg_dir.mkdir(parents=True)
            mod = pkg_dir / "service.py"
            mod.write_text("from ..storage import MemoryRepository\n", encoding="utf-8")

            with self.assertRaises(AssertionError):
                assert_pure_package(
                    self,
                    pkg_dir,
                    forbidden_modules=["asf.storage"],
                    src_dir=src_dir,
                )

    def test_clock_call_is_caught(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            clock_file = tmppath / "clock.py"
            clock_file.write_text(
                "import datetime\n\ndef get_time():\n    return datetime.datetime.now()\n",
                encoding="utf-8",
            )

            with self.assertRaises(AssertionError):
                assert_pure_package(self, tmppath)

    def test_include_and_exclude_filters(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            clean_file = tmppath / "clean.py"
            clean_file.write_text("x = 1\n", encoding="utf-8")
            dirty_file = tmppath / "dirty.py"
            dirty_file.write_text("import os\n", encoding="utf-8")

            # Exclude dirty.py -> passes
            assert_pure_package(self, tmppath, exclude=["dirty.py"])

            # Include clean.py -> passes
            assert_pure_package(self, tmppath, include=["clean.py"])
