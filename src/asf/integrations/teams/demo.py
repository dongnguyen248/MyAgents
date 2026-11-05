"""Manual no-bot Teams approval loop: Spec -> approval/revision -> Plan.

    .\\.venv\\Scripts\\python.exe -m asf.integrations.teams.demo --send

The command contacts your Power Automate flow. Without --gemini, model replies
are deterministic, not a demonstration of real LLM reasoning.
--gemini additionally calls Gemini using ASF_LIVE_GEMINI_MODEL and
ASF_LIVE_GEMINI_API_KEY; existing gateway limits apply across both agents.
No live command is run by automated tests.
"""

from __future__ import annotations

import argparse
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import uvicorn

from asf.agents.base import AgentRuntime
from asf.agents.loading import (
    load_plan_prompts,
    load_plan_template,
    load_spec_prompts,
    load_spec_template,
)
from asf.agents.plan.agent import PlanAgent
from asf.agents.spec.agent import SpecAgent
from asf.approval.models import ApprovalPolicy
from asf.configuration import load_platform_config
from asf.contracts.models import ModelRequest, ModelResponse
from asf.integrations.gemini import EvidenceCapture, GeminiModelGateway
from asf.integrations.teams.config import TeamsConfig
from asf.integrations.teams.workflow import TeamsWorkflow, create_app
from asf.models.fake import ScriptedModelGateway
from asf.models.ports import ModelGateway
from asf.orchestrator import AgentRegistry, Orchestrator
from asf.storage.sqlite import SQLiteExecutionStore
from asf.workflow.definition import WorkflowDefinition, WorkflowStepDef


class DemoModels:
    """Deterministic replies for real SpecAgent/PlanAgent wiring, not a live model."""

    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request.model_copy(deep=True))
        message = request.messages[-1].content
        linked = re.search(r"## Linked SPEC\nID: ([^\n]+)\nVersion: ([^\n]+)", message)
        if linked:
            template = load_plan_template(Path("templates"))
            sections = {
                "## Linked SPEC": f"ID: {linked[1]}\nVersion: {linked[2]}",
                "## Milestones": (
                    "### M1: Demonstrate approved SPEC handoff\n"
                    "- Deliverables: Demo PLAN\n"
                    "- Acceptance criteria: PLAN uses approved SPEC\n- Depends on: none"
                ),
            }
            reply = "# PLAN: Teams demo\n\n" + "\n\n".join(
                f"{heading}\n{sections.get(heading, 'Deterministic demo plan content.')}"
                for heading in template.required_sections
            )
        else:
            template_spec = load_spec_template(Path("templates"))
            revision = "## Reviewer feedback" in message
            reply = "# SPEC: Teams demo\n\n" + "\n\n".join(
                f"{heading}\n"
                + ("Revised demo specification." if revision else "Initial demo specification.")
                for heading in template_spec.required_sections
            )
        return ScriptedModelGateway([reply]).complete(request)


def demo_engine(
    config: TeamsConfig,
    store: SQLiteExecutionStore,
    *,
    models: ModelGateway | None = None,
    execution_id: str | None = None,
) -> Orchestrator:
    first_id = iter([execution_id] if execution_id is not None else [])
    runtime = AgentRuntime(
        models=models if models is not None else DemoModels(),
        clock=lambda: datetime.now(timezone.utc),
        new_id=lambda: next(first_id, str(uuid4())),
    )
    registry = AgentRegistry()
    registry.register(
        SpecAgent(
            runtime,
            prompts=load_spec_prompts(),
            template=load_spec_template(Path("templates")),
        )
    )
    registry.register(
        PlanAgent(
            runtime,
            prompts=load_plan_prompts(),
            template=load_plan_template(Path("templates")),
        )
    )
    return Orchestrator(
        WorkflowDefinition(
            id="teams-workflow-demo",
            name="Teams Workflows approval demo",
            version="2",
            steps=[
                WorkflowStepDef(
                    id="spec",
                    name="Specification",
                    type="AGENT",
                    stage="SPEC",
                    requires_approval=True,
                    agent_type="spec",
                    produces=["SPEC"],
                    max_revisions=3,
                ),
                WorkflowStepDef(
                    id="plan",
                    name="Plan after human approval",
                    type="AGENT",
                    stage="PLAN",
                    requires_approval=False,
                    agent_type="plan",
                    consumes=["SPEC"],
                    produces=["PLAN"],
                ),
            ],
        ),
        registry,
        clock=runtime.clock,
        new_id=runtime.new_id,
        store=store,
        approval_policy=ApprovalPolicy(
            reviewers=list(config.reviewers.values()),
            min_approvals=1,
            expires_in_seconds=3600,
        ),
    )


def run_demo(args: argparse.Namespace) -> None:
    if args.gemini and args.run_id:
        raise ValueError(
            "Live Gemini demo cannot resume: request budget is process-local; start a new demo",
        )
    platform = load_platform_config(args.config_dir)
    channels = [item for item in platform.notifications if item.name == args.channel]
    if len(channels) != 1:
        raise ValueError("Configure exactly one named Teams workflow notification channel")
    settings = TeamsConfig.from_channel(channels[0])
    execution_id = args.run_id or str(uuid4())
    models: ModelGateway | None = None
    if args.gemini:
        models = GeminiModelGateway.from_environment(
            model=os.environ.get("ASF_LIVE_GEMINI_MODEL", ""),
            evidence=EvidenceCapture(
                Path(".asf-evidence"),
                secrets=[os.environ.get("ASF_LIVE_GEMINI_API_KEY", "")],
            ),
            run_id=execution_id,
        )
    store = SQLiteExecutionStore(args.database)
    try:
        engine = demo_engine(
            settings,
            store,
            models=models,
            execution_id=None if args.run_id else execution_id,
        )
        run = (
            engine.get(args.run_id)
            if args.run_id
            else engine.start(
                task_id="teams-demo",
                project_id="teams-demo",
                inputs={"spec": {"requirement": args.requirement}},
            )
        )
        workflow = TeamsWorkflow(settings, engine)
        app = create_app(workflow, run.id)
        print(f"Demo run: {run.id}; stage: {run.state.stage}")
        uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)
    finally:
        store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-dir", type=Path, default=Path("config"))
    parser.add_argument("--channel", default="teams-approvals")
    parser.add_argument(
        "--database",
        type=Path,
        default=Path("artifacts/teams-workflow-demo.sqlite"),
    )
    parser.add_argument("--run-id", help="Resume a workflow demo; may resend its current card")
    parser.add_argument("--port", type=int, default=3978)
    parser.add_argument(
        "--requirement",
        default="Demonstrate Teams approval and SPEC-to-PLAN handoff",
    )
    parser.add_argument(
        "--send",
        action="store_true",
        help="Acknowledge real Teams workflow delivery",
    )
    parser.add_argument("--gemini", action="store_true", help="Also enable real Gemini model calls")
    args = parser.parse_args()
    if not args.send:
        parser.error("--send is required: this manual demo contacts Teams Workflows")
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    run_demo(args)


if __name__ == "__main__":
    main()
