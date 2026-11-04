"""GitLab adapter for the hosting port (REST API v4).

Works against gitlab.com and self-hosted instances: the API base is
derived from the repository URL (``https://<host>/api/v4``) and the
project is addressed by its URL-encoded path, so nested groups are
fine. Pushes use the Commits API — one atomic commit per change set,
no local clone needed. Authentication is a personal/project access
token sent as ``PRIVATE-TOKEN`` (never stored in the profile; the
factory resolves it from an environment variable).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote, urlencode

from asf.integrations.hosting.http import JsonHttpClient, Transport
from asf.integrations.hosting.ports import (
    ChangeRequestRef,
    HostingError,
    PipelineRef,
    PushResult,
)
from asf.tools.changeset import ChangeSet

__all__ = ["GitLabProvider"]

_ACTION_MAP = {"create": "create", "modify": "update", "delete": "delete"}

_PIPELINE_MAP = {
    "success": "PASS",
    "failed": "FAIL",
    "running": "RUNNING",
    "pending": "RUNNING",
    "preparing": "RUNNING",
    "created": "RUNNING",
    "waiting_for_resource": "RUNNING",
    "scheduled": "RUNNING",
    "manual": "RUNNING",
    "canceled": "UNKNOWN",
    "skipped": "UNKNOWN",
}


class GitLabProvider:
    def __init__(
        self,
        api_base: str,
        project_path: str,
        token: str | None,
        transport: Transport | None = None,
    ) -> None:
        headers = {"PRIVATE-TOKEN": token} if token else {}
        self._http = JsonHttpClient(api_base, headers, transport)
        self._project = quote(project_path, safe="")

    # -- writes ------------------------------------------------------------
    def push_changeset(
        self, *, branch: str, base_branch: str, changes: ChangeSet, message: str,
    ) -> PushResult:
        actions: list[dict[str, Any]] = []
        for change in changes.changes:
            action: dict[str, Any] = {
                "action": _ACTION_MAP[change.operation],
                "file_path": change.path,
            }
            if change.content is not None:
                action["content"] = change.content
            actions.append(action)
        payload: dict[str, Any] = {
            "branch": branch,
            "start_branch": base_branch,
            "commit_message": message,
            "actions": actions,
        }
        try:
            data = self._http.request(
                "POST", f"/projects/{self._project}/repository/commits", payload,
            )
        except HostingError as error:
            if error.status != 400 or "already exists" not in str(error):
                raise
            # The branch is already there (a previous run pushed it):
            # commit on top of it instead of recreating it.
            payload.pop("start_branch")
            data = self._http.request(
                "POST", f"/projects/{self._project}/repository/commits", payload,
            )
        return PushResult(branch=branch, commit_sha=str(data["id"]))

    def open_change_request(
        self, *, branch: str, base_branch: str, title: str, description: str,
    ) -> ChangeRequestRef:
        existing = self._merge_requests(branch, state="opened")
        if existing:
            return _to_ref(existing[0])
        data = self._http.request(
            "POST",
            f"/projects/{self._project}/merge_requests",
            {
                "source_branch": branch,
                "target_branch": base_branch,
                "title": title,
                "description": description,
                "remove_source_branch": False,
            },
        )
        return _to_ref(data)

    # -- reads -------------------------------------------------------------
    def change_request(self, *, branch: str) -> ChangeRequestRef | None:
        found = self._merge_requests(branch, state="all")
        return _to_ref(found[0]) if found else None

    def pipeline_status(self, *, branch: str) -> PipelineRef | None:
        query = urlencode({"ref": branch, "per_page": 1})
        data = self._http.request(
            "GET", f"/projects/{self._project}/pipelines?{query}",
        )
        if not isinstance(data, list) or not data:
            return None
        latest = data[0]
        return PipelineRef(
            id=str(latest["id"]),
            status=_PIPELINE_MAP.get(str(latest.get("status")), "UNKNOWN"),
            url=str(latest.get("web_url", "")),
        )

    def _merge_requests(self, branch: str, *, state: str) -> list[dict[str, Any]]:
        query = urlencode({
            "source_branch": branch,
            "state": state,
            "order_by": "created_at",
            "sort": "desc",
            "per_page": 1,
        })
        data = self._http.request(
            "GET", f"/projects/{self._project}/merge_requests?{query}",
        )
        return data if isinstance(data, list) else []


def _to_ref(data: dict[str, Any]) -> ChangeRequestRef:
    state = {"opened": "open", "merged": "merged", "closed": "closed"}.get(
        str(data.get("state")), "open",
    )
    return ChangeRequestRef(
        id=str(data.get("iid", "")),
        url=str(data.get("web_url", "")),
        state=state,
        branch=str(data.get("source_branch", "")),
    )
