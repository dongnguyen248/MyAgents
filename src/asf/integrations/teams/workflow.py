from __future__ import annotations

import asyncio
import hmac
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from asf.approval.errors import ApprovalError
from asf.configuration.platform import ConfigModel
from asf.integrations.gemini import HttpTransport, UrlLibTransport, _ResponseTooLargeError
from asf.integrations.teams.approval import TeamsAction, TeamsActor, TeamsApprovals
from asf.integrations.teams.cards import approval_card
from asf.integrations.teams.config import TeamsConfig
from asf.orchestrator import Orchestrator
from asf.orchestrator.execution import WorkflowExecution

logger = logging.getLogger(__name__)
MAX_CALLBACK_BYTES = 16_384
MAX_CARD_BYTES = 28_000
TERMINAL = frozenset({"COMPLETED", "FAILED", "CANCELLED"})


class TeamsDeliveryError(RuntimeError):
    code = "INTEGRATION_UNAVAILABLE"


class WorkflowDecision(ConfigModel):
    actor: TeamsActor
    action: TeamsAction


class TeamsWorkflow:
    """One trusted Power Automate flow, with explicit at-least-once card delivery."""

    def __init__(
        self, config: TeamsConfig, engine: Orchestrator, *, transport: HttpTransport | None = None,
    ) -> None:
        self.approvals = TeamsApprovals(config, engine)
        self._url = config.resolve_workflow_url()
        self._callback_secret = config.callback_secret.resolve()
        if (
            len(self._callback_secret) < 32
            or not self._callback_secret.isascii() or not self._callback_secret.isprintable()
            or any(char.isspace() for char in self._callback_secret)
        ):
            raise ValueError("Teams callback secret must contain at least 32 characters")
        self._transport = transport or UrlLibTransport()
        self._sent: set[str] = set()
        self.failure_code: str | None = None

    def authenticated(self, authorization: str) -> bool:
        return hmac.compare_digest(
            authorization.encode("utf-8"), ("Bearer " + self._callback_secret).encode("utf-8"),
        )

    def send_approval(self, run_id: str) -> None:
        request = self.approvals.pending(run_id)
        run = self.approvals.engine.get(run_id)
        artifact = run.artifact_history[request.artifact_id]
        card = approval_card(run_id, request, artifact)
        serialized_card = json.dumps(card, ensure_ascii=False).encode("utf-8")
        if len(serialized_card) > MAX_CARD_BYTES:
            raise TeamsDeliveryError("Approval card too large; no partial specification was sent")
        config = self.approvals.config
        payload = {
            "runId": run_id, "approvalId": request.id,
            "artifactId": artifact.id, "artifactVersion": artifact.version,
            "tenantId": str(config.tenant_id), "teamId": str(config.team_id),
            "channelId": config.channel_id, "card": card,
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if self._callback_secret.encode("utf-8") in body or self._url.encode("utf-8") in body:
            raise TeamsDeliveryError("Approval artifact contains configured credential material")
        try:
            status, _headers, _body = self._transport.post(
                self._url, headers={"Content-Type": "application/json"}, body=body,
                timeout_seconds=config.timeout_seconds, max_response_bytes=4096,
            )
        except (OSError, ValueError, _ResponseTooLargeError):
            raise TeamsDeliveryError("Teams workflow delivery failed; retry explicitly") from None
        if status not in (200, 201, 202, 204):
            raise TeamsDeliveryError("Teams workflow did not accept the approval request")
        self._sent.add(request.id)

    def decide(self, decision: WorkflowDecision) -> WorkflowExecution:
        if any(secret in decision.action.comment for secret in (self._url, self._callback_secret)):
            raise ApprovalError("VALIDATION_FAILED", "Feedback must not contain credentials")
        result = self.approvals.decide(decision.actor, decision.action)
        if result.approval_id == decision.action.approval_id:
            # A single-response flow needs a fresh card for the remaining quorum.
            self._sent.discard(decision.action.approval_id)
        return result

    def advance(self, run_id: str) -> WorkflowExecution:
        engine = self.approvals.engine
        run = engine.get(run_id)
        if (
            engine.workflow_run(run_id)["status"] in TERMINAL
            or run.state.stage.endswith("_ESCALATED")
        ):
            return run
        run = engine.tick(run_id)
        if run.approval_id is not None and run.approval_id not in self._sent:
            self.send_approval(run_id)
        return run


def create_app(
    workflow: TeamsWorkflow, run_id: str, *, poll_seconds: float = 1,
) -> FastAPI:
    """Run callbacks and automatic agent dispatch on one SQLite-owning event-loop thread."""
    if poll_seconds <= 0:
        raise ValueError("Polling interval must be positive")
    engine = workflow.approvals.engine
    engine.get(run_id)

    async def drive() -> None:
        while True:
            try:
                run = workflow.advance(run_id)
            except (TeamsDeliveryError, ApprovalError, ValueError, KeyError) as error:
                workflow.failure_code = (
                    error.code if isinstance(error, (TeamsDeliveryError, ApprovalError))
                    else "AGENT_EXECUTION_FAILED"
                )
                logger.error("Teams automatic execution paused: %s", workflow.failure_code)
                return
            if (
                engine.workflow_run(run_id)["status"] in TERMINAL
                or run.state.stage.endswith("_ESCALATED")
            ):
                logger.info("Teams workflow stopped at stage %s", run.state.stage)
                return
            await asyncio.sleep(poll_seconds)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        task = asyncio.create_task(drive())
        app.state.driver = task
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    def response(status: int, code: str) -> JSONResponse:
        return JSONResponse(status_code=status, content={"code": code})

    def failure_code() -> str | None:
        if workflow.failure_code:
            return workflow.failure_code
        task = getattr(app.state, "driver", None)
        if task is not None and task.done() and (task.cancelled() or task.exception() is not None):
            return "AGENT_EXECUTION_FAILED"
        return None

    @app.get("/health")
    async def health() -> JSONResponse:
        failure = failure_code()
        if failure is not None:
            return response(503, failure)
        return response(200, "OK")

    @app.post("/api/teams/decisions")
    async def decide(request: Request) -> JSONResponse:
        if not workflow.authenticated(request.headers.get("authorization", "")):
            logger.warning("Teams callback rejected: unauthorized")
            return response(401, "APPROVAL_NOT_AUTHORIZED")
        failure = failure_code()
        if failure is not None:
            return response(503, failure)
        raw = bytearray()
        async for part in request.stream():
            if len(raw) + len(part) > MAX_CALLBACK_BYTES:
                return response(413, "VALIDATION_FAILED")
            raw.extend(part)
        try:
            decision = WorkflowDecision.model_validate_json(raw)
        except ValidationError:
            logger.warning("Teams callback rejected: invalid payload")
            return response(422, "VALIDATION_FAILED")
        if decision.action.run_id != run_id:
            return response(403, "APPROVAL_NOT_AUTHORIZED")
        try:
            result = workflow.decide(decision)
        except ApprovalError as error:
            logger.warning("Teams callback rejected: %s", error.code)
            statuses: dict[str, Literal[403, 404, 409, 410, 422]] = {
                "APPROVAL_NOT_AUTHORIZED": 403, "NOT_FOUND": 404,
                "APPROVAL_ALREADY_DECIDED": 409, "APPROVAL_EXPIRED": 410,
                "VALIDATION_FAILED": 422,
            }
            return response(statuses[error.code], error.code)
        return JSONResponse(status_code=200, content={
            "code": "DECISION_RECORDED", "stage": result.state.stage,
            "approvalPending": result.approval_id == decision.action.approval_id,
        })

    return app
