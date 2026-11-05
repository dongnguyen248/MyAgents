"""FastAPI adapter for :class:`~asf.api.service.FactoryService`.

The route paths are exactly the ones the dashboard's ``httpApi.ts`` calls.
FastAPI is imported at module level here (as in
``asf.integrations.teams.workflow``); the ``asf.api`` package ``__init__``
only re-exports the framework-free service, so importing the package never
requires FastAPI.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import Body, FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

from asf.api.service import (
    FactoryService,
    ProjectConflictError,
    ProjectExistsError,
    ProjectNotFoundError,
)
from asf.approval.errors import ApprovalError

__all__ = ["create_app"]


class DecisionBody(BaseModel):
    decision: str
    comment: str = ""


class RunBody(BaseModel):
    taskId: str
    projectId: str
    inputs: dict[str, Any] | None = None
    context: dict[str, Any] | None = None


class ModelSettingsBody(BaseModel):
    provider: str
    model: str = ""
    baseUrl: str = ""
    apiKey: str | None = None
    clearKey: bool = False
    agentModels: dict[str, str] | None = None


class ModelTestBody(BaseModel):
    agent: str | None = None


def _not_found(what: str) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": f"{what} not found"})


def create_app(service: FactoryService) -> FastAPI:
    """Build the dashboard REST + SSE application around ``service``."""
    app = FastAPI(title="AI Software Agents API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    # -- agents ---------------------------------------------------------
    @app.get("/agents")
    async def list_agents() -> list[dict[str, Any]]:
        return service.list_agents()

    @app.get("/agents/{agent_id}")
    async def get_agent(agent_id: str) -> Any:
        agent = service.get_agent(agent_id)
        return agent if agent is not None else _not_found("Agent")

    @app.get("/agents/{agent_id}/config")
    async def get_agent_config(agent_id: str) -> Any:
        config = service.get_agent_config(agent_id)
        return config if config is not None else _not_found("Agent")

    @app.get("/agents/{agent_id}/runs")
    async def get_agent_runs(agent_id: str) -> list[dict[str, Any]]:
        return service.get_agent_runs(agent_id)

    # -- tasks ----------------------------------------------------------
    @app.get("/tasks")
    async def list_tasks(
        projectId: str | None = None,
        agentId: str | None = None,
        status: str | None = None,
        workflowType: str | None = None,
        priority: str | None = None,
        sinceHours: float | None = None,
    ) -> list[dict[str, Any]]:
        criteria = {
            key: value
            for key, value in {
                "projectId": projectId,
                "agentId": agentId,
                "status": status,
                "workflowType": workflowType,
                "priority": priority,
                "sinceHours": sinceHours,
            }.items()
            if value is not None
        }
        return service.list_tasks(criteria)

    @app.get("/tasks/{task_id}")
    async def get_task(task_id: str) -> Any:
        task = service.get_task(task_id)
        return task if task is not None else _not_found("Task")

    # -- workflows --------------------------------------------------------
    @app.get("/workflows")
    async def list_workflows() -> list[dict[str, Any]]:
        return service.list_workflows()

    @app.get("/workflows/{workflow_id}")
    async def get_workflow(workflow_id: str) -> Any:
        workflow = service.get_workflow(workflow_id)
        return workflow if workflow is not None else _not_found("Workflow")

    # -- projects ---------------------------------------------------------
    @app.get("/projects")
    async def list_projects() -> list[dict[str, Any]]:
        return service.list_projects()

    @app.post("/projects", status_code=201)
    async def create_project(payload: dict[str, Any] = Body(...)) -> Any:
        try:
            return service.create_project(payload)
        except ProjectExistsError as error:
            return JSONResponse(status_code=409, content={"detail": str(error)})
        except ValueError as error:
            return JSONResponse(status_code=422, content={"detail": str(error)})

    @app.put("/projects/{project_id}")
    async def update_project(
        project_id: str,
        payload: dict[str, Any] = Body(...),
    ) -> Any:
        try:
            return service.update_project(project_id, payload)
        except ProjectNotFoundError:
            return _not_found("Project")
        except ValueError as error:
            return JSONResponse(status_code=422, content={"detail": str(error)})

    @app.delete("/projects/{project_id}")
    async def delete_project(project_id: str) -> Any:
        try:
            service.delete_project(project_id)
        except ProjectNotFoundError:
            return _not_found("Project")
        except ProjectConflictError as error:
            return JSONResponse(status_code=409, content={"detail": str(error)})
        return Response(status_code=204)

    # -- approvals --------------------------------------------------------
    @app.get("/approvals")
    async def list_approvals() -> list[dict[str, Any]]:
        return service.list_approvals()

    @app.post("/approvals/{approval_id}/decision")
    async def decide_approval(approval_id: str, body: DecisionBody) -> Any:
        try:
            return service.decide_approval(
                approval_id,
                decision=body.decision,
                comment=body.comment,
            )
        except ApprovalError as error:
            return JSONResponse(status_code=409, content={"detail": error.code})
        except ValueError as error:
            return JSONResponse(status_code=422, content={"detail": str(error)})

    # -- activity / metrics ----------------------------------------------
    @app.get("/activity")
    async def list_activity(
        agentId: str | None = None,
        taskId: str | None = None,
        projectId: str | None = None,
        limit: int | None = Query(default=None, ge=1),
    ) -> list[dict[str, Any]]:
        criteria = {
            key: value
            for key, value in {
                "agentId": agentId,
                "taskId": taskId,
                "projectId": projectId,
                "limit": limit,
            }.items()
            if value is not None
        }
        return service.list_activity(criteria)

    @app.get("/metrics/overview")
    async def metrics_overview() -> dict[str, Any]:
        return service.get_metrics_overview()

    @app.get("/settings/model")
    def get_model_settings() -> Any:
        settings = service.get_model_settings()
        if settings is None:
            return _not_found("Model settings")
        return settings

    @app.put("/settings/model")
    def update_model_settings(body: ModelSettingsBody) -> Any:
        payload: dict[str, Any] = {
            "provider": body.provider,
            "model": body.model,
            "baseUrl": body.baseUrl,
            "clearKey": body.clearKey,
        }
        if body.apiKey:
            payload["apiKey"] = body.apiKey
        if body.agentModels is not None:
            payload["agentModels"] = body.agentModels
        try:
            updated = service.update_model_settings(payload)
        except ValueError as error:
            return JSONResponse(status_code=422, content={"detail": str(error)})
        if updated is None:
            return _not_found("Model settings")
        return updated

    @app.post("/settings/model/test")
    def test_model_settings(body: ModelTestBody | None = None) -> Any:
        result = service.test_model_settings(
            agent=body.agent if body is not None else None,
        )
        if result is None:
            return _not_found("Model settings")
        return result

    @app.get("/events")
    async def events(request: Request) -> StreamingResponse:
        async def stream() -> AsyncIterator[str]:
            seen: set[str] = set()
            while True:
                if await request.is_disconnected():
                    return
                fresh = [
                    event
                    for event in service.list_activity({"limit": 500})
                    if event["id"] not in seen
                ]
                for event in reversed(fresh):  # emit chronologically
                    seen.add(event["id"])
                    yield f"data: {json.dumps(event)}\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(stream(), media_type="text/event-stream")

    # -- run control -------------------------------------------------------
    @app.post("/runs", status_code=201)
    async def start_run(body: RunBody) -> Any:
        try:
            run = service.start_run(
                body.taskId,
                body.projectId,
                inputs=body.inputs,
                context=body.context,
            )
        except ValueError as error:
            return JSONResponse(status_code=422, content={"detail": str(error)})
        return service.get_workflow(run.id)

    @app.post("/runs/{run_id}/tick")
    async def tick_run(run_id: str) -> Any:
        try:
            return service.tick_run(run_id)
        except KeyError:
            return _not_found("Run")
        except ValueError as error:
            return JSONResponse(status_code=409, content={"detail": str(error)})

    @app.post("/runs/{run_id}/cancel")
    async def cancel_run(run_id: str) -> Any:
        try:
            return service.cancel_run(run_id)
        except KeyError:
            return _not_found("Run")
        except ValueError as error:
            return JSONResponse(status_code=409, content={"detail": str(error)})

    @app.post("/runs/{run_id}/retry", status_code=201)
    async def retry_run(run_id: str) -> Any:
        try:
            return service.retry_run(run_id)
        except KeyError:
            return _not_found("Run")
        except ValueError as error:
            return JSONResponse(status_code=409, content={"detail": str(error)})

    @app.post("/runs/{run_id}/resume", status_code=201)
    async def resume_run(run_id: str) -> Any:
        try:
            return service.resume_run(run_id)
        except KeyError:
            return _not_found("Run")
        except ValueError as error:
            return JSONResponse(status_code=409, content={"detail": str(error)})

    return app
