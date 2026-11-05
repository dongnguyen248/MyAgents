"""Per-project hosting access tokens, managed from the dashboard.

Each project can carry its own GitLab/GitHub token (different projects
live on different instances with different credentials), entered in the
project form. The token itself is stored ONLY here — a JSON file beside
the run database — never in the project profile: profiles are
user-editable YAML, persisted by the project hooks, echoed in views and
safe to share, so a secret must not ride along in them.

Reads and writes go through this store; the API surface exposes only
whether a token is configured plus a last-4 hint, mirroring the model
provider settings. Resolution order for a run's CI steps: the stored
per-project token wins; the profile's environment variable
(``repository.tokenEnv``, default ``ASF_GITLAB_TOKEN`` /
``ASF_GITHUB_TOKEN``) remains the fallback.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path


class HostingTokens:
    """Project-id -> access token map, persisted when given a path."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._tokens: dict[str, str] = {}
        if path is not None and path.is_file():
            try:
                stored = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                stored = None
            if isinstance(stored, dict):
                self._tokens = {
                    str(project_id): token
                    for project_id, token in stored.items()
                    if isinstance(token, str) and token
                }

    def get(self, project_id: str) -> str | None:
        with self._lock:
            return self._tokens.get(project_id)

    def hint(self, project_id: str) -> str | None:
        """A last-4 hint for display (``"…ab12"``), never the token."""
        token = self.get(project_id)
        if not token:
            return None
        return f"…{token[-4:]}" if len(token) >= 4 else "…"

    def set(self, project_id: str, token: str) -> None:
        token = token.strip()
        if not token:
            raise ValueError("Hosting token must not be blank")
        with self._lock:
            self._tokens[project_id] = token
            self._save()

    def clear(self, project_id: str) -> None:
        with self._lock:
            if self._tokens.pop(project_id, None) is not None:
                self._save()

    def _save(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._tokens, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
