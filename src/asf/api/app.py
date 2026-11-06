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


def _operator(request: Request) -> str:
    return request.headers.get("x-operator") or "operator"


def _reason(payload: dict[str, Any]) -> str | JSONResponse:
    reason = payload.get("reason")
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 500:
        return JSONResponse(
            status_code=422,
            content={"detail": "reason is required (non-empty, at most 500 characters)"},
        )
    return reason.strip()


def _register_escalation_routes(app: FastAPI, service: FactoryService) -> None:
    """The two operator actions on an escalated run.

    Resume restarts the revision window (optionally carrying a
    guidance comment to the producer); approve-anyway accepts
    the escalated gate's artifact. Both carry a validated reason
    and the X-Operator identity into the run's audit events.
    """
    _register_resume_route(app, service)
    _register_approve_route(app, service)


def _register_resume_route(app: FastAPI, service: FactoryService) -> None:
    @app.post("/runs/{run_id}/escalation/resume")
    async def resume_escalation(
        run_id: str, request: Request, payload: dict[str, Any] = Body(...)
    ) -> Any:
        reason = _reason(payload)
        if isinstance(reason, JSONResponse):
            return reason
        guidance = payload.get("guidance")
        if guidance is not None and (not isinstance(guidance, str) or len(guidance) > 4000):
            return JSONResponse(
                status_code=422,
                content={"detail": "guidance must be a string of at most 4000 characters"},
            )
        try:
            view = service.resume_escalation(
                run_id, reason=reason, operator=_operator(request), guidance=guidance
            )
        except KeyError:
            return _not_found("Run")
        except ValueError as error:
            return JSONResponse(status_code=409, content={"detail": str(error)})
        return view if view is not None else _not_found("Run")


def _register_approve_route(app: FastAPI, service: FactoryService) -> None:
    @app.post("/runs/{run_id}/escalation/approve")
    async def approve_escalation(
        run_id: str, request: Request, payload: dict[str, Any] = Body(...)
    ) -> Any:
        reason = _reason(payload)
        if isinstance(reason, JSONResponse):
            return reason
        try:
            view = service.approve_escalation(run_id, reason=reason, operator=_operator(request))
        except KeyError:
            return _not_found("Run")
        except ValueError as error:
            return JSONResponse(status_code=409, content={"detail": str(error)})
        return view if view is not None else _not_found("Run")


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

    @app.get("/runs/{run_id}/diagnostics")
    async def run_diagnostics(run_id: str) -> Any:
        diagnostics = service.run_diagnostics(run_id)
        return diagnostics if diagnostics is not None else _not_found("Run")

    @app.get("/runs/{run_id}/reviews")
    async def run_reviews(run_id: str) -> Any:
        reviews = service.run_reviews(run_id)
        return reviews if reviews is not None else _not_found("Run")

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

    # -- operator run controls -------------------------------------
    # Every action carries a reason (validated here: required,
    # non-blank, <= 500 chars -> 422) and the operator identity
    # from the X-Operator header (default "operator"); both land
    # in the run's audit events. State the action does not allow
    # and lost version races surface as 409 via the service.
    _register_escalation_routes(app, service)

    @app.post("/runs/{run_id}/recover")
    async def recover_run(
        run_id: str, request: Request, payload: dict[str, Any] = Body(...)
    ) -> Any:
        reason = _reason(payload)
        if isinstance(reason, JSONResponse):
            return reason
        try:
            view = service.recover_run(
                run_id,
                reason=reason,
                retry_interrupted=bool(payload.get("retryInterrupted", False)),
                operator=_operator(request),
            )
        except KeyError:
            return _not_found("Run")
        except ValueError as error:
            return JSONResponse(status_code=409, content={"detail": str(error)})
        return view if view is not None else _not_found("Run")

    @app.post("/runs/{run_id}/drive")
    async def drive_run(run_id: str) -> Any:
        try:
            view = service.drive_run(run_id)
        except KeyError:
            return _not_found("Run")
        return view if view is not None else _not_found("Run")

    @app.post("/runs/{run_id}/fail")
    async def fail_run(run_id: str, request: Request, payload: dict[str, Any] = Body(...)) -> Any:
        reason = _reason(payload)
        if isinstance(reason, JSONResponse):
            return reason
        try:
            view = service.fail_run(run_id, reason=reason, operator=_operator(request))
        except KeyError:
            return _not_found("Run")
        except ValueError as error:
            return JSONResponse(status_code=409, content={"detail": str(error)})
        return view if view is not None else _not_found("Run")

    @app.post("/runs/{run_id}/pause")
    async def pause_run(
        run_id: str, request: Request, payload: dict[str, Any] = Body(default={})
    ) -> Any:
        reason = payload.get("reason")
        try:
            view = service.pause_run(
                run_id,
                reason=reason.strip() if isinstance(reason, str) else "",
                operator=_operator(request),
            )
        except KeyError:
            return _not_found("Run")
        except ValueError as error:
            return JSONResponse(status_code=409, content={"detail": str(error)})
        return view if view is not None else _not_found("Run")

    @app.post("/runs/{run_id}/continue")
    async def continue_run(
        run_id: str, request: Request, payload: dict[str, Any] = Body(default={})
    ) -> Any:
        reason = payload.get("reason")
        try:
            view = service.continue_run(
                run_id,
                reason=reason.strip() if isinstance(reason, str) else "",
                operator=_operator(request),
            )
        except KeyError:
            return _not_found("Run")
        except ValueError as error:
            return JSONResponse(status_code=409, content={"detail": str(error)})
        return view if view is not None else _not_found("Run")

    return app
