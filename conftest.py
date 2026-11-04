"""Repo-root conftest: make the repo root importable under pytest.

The runtime package lives under ``src/`` (installed), but the offline
``harness`` package lives at the repo root, so the root must be on
``sys.path`` for ``import harness...`` to work in tests and tooling.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
