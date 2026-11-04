"""GitHub adapter for the hosting port (REST API v3).

Works against github.com (``https://api.github.com``) and GitHub
Enterprise (``https://<host>/api/v3``). Pushes use the Git Data API —
tree + commit + ref — so a change set lands as one commit on the
branch with no local clone. Authentication is a token sent as
``Authorization: Bearer`` (never stored in the profile; the factory
resolves it from an environment variable). A missing token still
allows reads against public repositories.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from asf.integrations.hosting.http import JsonHttpClient, Transport
from asf.integrations.hosting.ports import (
    ChangeRequestRef,
    HostingError,
    PipelineRef,
    PushResult,
)
from asf.tools.changeset import ChangeSet

__all__ = ["GitHubProvider"]


class GitHubProvider:
    def __init__(
        self,
        api_base: str,
        owner: str,
        repo: str,
        token: str | None,
        transport: Transport | None = None,
    ) -> None:
        headers: dict[str, str] = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._http = JsonHttpClient(api_base, headers, transport)
        self._repo_path = f"/repos/{owner}/{repo}"
        self._owner = owner

    # -- writes ------------------------------------------------------------
    def push_changeset(
        self, *, branch: str, base_branch: str, changes: ChangeSet, message: str,
    ) -> PushResult:
        base_sha = self._ref_sha(base_branch)
        commit = self._http.request("GET", f"{self._repo_path}/git/commits/{base_sha}")
        tree_items: list[dict[str, Any]] = []
        for change in changes.changes:
            if change.operation == "delete":
                tree_items.append({
                    "path": change.path, "mode": "100644",
                    "type": "blob", "sha": None,
                })
            else:
                tree_items.append({
                    "path": change.path, "mode": "100644",
                    "type": "blob", "content": change.content or "",
                })
        tree = self._http.request(
            "POST",
            f"{self._repo_path}/git/trees",
            {"base_tree": commit["tree"]["sha"], "tree": tree_items},
        )
        new_commit = self._http.request(
            "POST",
            f"{self._repo_path}/git/commits",
            {"message": message, "tree": tree["sha"], "parents": [base_sha]},
        )
        new_sha = str(new_commit["sha"])
        try:
            self._ref_sha(branch)
        except HostingError as error:
            if error.status != 404:
                raise
            self._http.request(
                "POST",
                f"{self._repo_path}/git/refs",
                {"ref": f"refs/heads/{branch}", "sha": new_sha},
            )
        else:
            self._http.request(
                "PATCH",
                f"{self._repo_path}/git/refs/heads/{branch}",
                {"sha": new_sha, "force": False},
            )
        return PushResult(branch=branch, commit_sha=new_sha)

    def open_change_request(
        self, *, branch: str, base_branch: str, title: str, description: str,
    ) -> ChangeRequestRef:
        existing = self._pull_requests(branch, state="open")
        if existing:
            return self._to_ref(existing[0])
        data = self._http.request(
            "POST",
            f"{self._repo_path}/pulls",
            {
                "title": title,
                "head": branch,
                "base": base_branch,
                "body": description,
            },
        )
        return self._to_ref(data)

    # -- reads -------------------------------------------------------------
    def change_request(self, *, branch: str) -> ChangeRequestRef | None:
        found = self._pull_requests(branch, state="all")
        return self._to_ref(found[0]) if found else None

    def pipeline_status(self, *, branch: str) -> PipelineRef | None:
        data = self._http.request(
            "GET", f"{self._repo_path}/commits/{branch}/check-runs?per_page=100",
        )
        runs = data.get("check_runs") if isinstance(data, dict) else None
        if isinstance(runs, list) and runs:
            if any(run.get("status") != "completed" for run in runs):
                status = "RUNNING"
            else:
                conclusions = {str(run.get("conclusion")) for run in runs}
                if conclusions <= {"success", "neutral", "skipped"}:
                    status = "PASS"
                elif conclusions & {
                    "failure", "timed_out", "action_required", "startup_failure",
                }:
                    status = "FAIL"
                else:
                    status = "UNKNOWN"
            return PipelineRef(id=f"check-runs:{branch}", status=status, url="")
        combined = self._http.request(
            "GET", f"{self._repo_path}/commits/{branch}/status",
        )
        if isinstance(combined, dict) and combined.get("total_count"):
            status = {
                "success": "PASS", "pending": "RUNNING",
                "failure": "FAIL", "error": "FAIL",
            }.get(str(combined.get("state")), "UNKNOWN")
            return PipelineRef(
                id=f"status:{branch}", status=status,
                url=str(combined.get("target_url", "") or ""),
            )
        return None

    # -- helpers -------------------------------------------------------------
    def _ref_sha(self, branch: str) -> str:
        data = self._http.request(
            "GET", f"{self._repo_path}/git/ref/heads/{branch}",
        )
        return str(data["object"]["sha"])

    def _pull_requests(self, branch: str, *, state: str) -> list[dict[str, Any]]:
        query = urlencode({
            "head": f"{self._owner}:{branch}",
            "state": state,
            "sort": "created",
            "direction": "desc",
            "per_page": 1,
        })
        data = self._http.request("GET", f"{self._repo_path}/pulls?{query}")
        return data if isinstance(data, list) else []

    @staticmethod
    def _to_ref(data: dict[str, Any]) -> ChangeRequestRef:
        if data.get("merged_at"):
            state = "merged"
        elif data.get("state") == "open":
            state = "open"
        else:
            state = "closed"
        return ChangeRequestRef(
            id=str(data.get("number", "")),
            url=str(data.get("html_url", "")),
            state=state,
            branch=str((data.get("head") or {}).get("ref", "")),
        )
