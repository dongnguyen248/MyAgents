from __future__ import annotations

import copy
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from asf.agents.base import AgentRuntime
from asf.agents.loading import load_plan_prompts, load_plan_template
from asf.agents.plan.agent import PlanAgent
from asf.agents.plan.milestones import milestone_ancestors, parse_milestones
from asf.contracts.models import (
    AgentRequest,
    ApprovalFeedback,
    Artifact,
)
from asf.models.errors import ModelGatewayError
from asf.models.fake import ScriptedModelGateway
from tests.unit.contract_models import validator_for

REPO_ROOT = Path(__file__).resolve().parents[2]
T_AWARE = datetime(2026, 10, 20, 14, 0, 0, tzinfo=timezone.utc)


def counter_id(prefix: str = "id-"):
    count = 0

    def _next() -> str:
        nonlocal count
        count += 1
        return f"{prefix}{count}"

    return _next


def make_valid_plan_reply(
    template_sections: list[str],
    *,
    spec_id: str = "spec-123",
    spec_version: str = "1",
) -> str:
    """Creates a valid PLAN reply with all required sections and valid milestones."""
    lines = ["# PLAN: Test Plan"]
    for sec in template_sections:
        lines.append(sec)
        if sec == "## Linked SPEC":
            lines.append(f"ID: {spec_id}")
            lines.append(f"Version: {spec_version}")
        else:
            lines.append("Section details content.")
    # Add valid milestones
    lines.append("## Milestones")
    lines.append("### M1: Setup")
    lines.append("- Deliverables: Project scaffold")
    lines.append("- Acceptance criteria: Project builds and runs")
    lines.append("- Depends on: none")
    lines.append("### M2: Core Implementation")
    lines.append("- Deliverables: Core modules")
    lines.append("- Acceptance criteria: All unit tests pass")
    lines.append("- Depends on: M1")
    return "\n\n".join(lines)


class PlanAgentTests(unittest.TestCase):
    def setUp(self):
        self.prompts = load_plan_prompts()
        self.template = load_plan_template(REPO_ROOT / "templates")
        self.valid_reply = make_valid_plan_reply(
            self.template.required_sections,
            spec_id="spec-123",
            spec_version="1",
        )

    def _make_agent(
        self,
        script: list[Any],
        *,
        model: str | None = "test-model",
        parameters: dict[str, Any] | None = None,
        clock=None,
        new_id=None,
    ) -> tuple[PlanAgent, ScriptedModelGateway]:
        gateway = ScriptedModelGateway(script)
        clk = clock or (lambda: T_AWARE)
        nid = new_id or counter_id("gen-")
        runtime = AgentRuntime(models=gateway, clock=clk, new_id=nid)
        agent = PlanAgent(
            runtime,
            prompts=self.prompts,
            template=self.template,
            model=model,
            parameters=parameters or {"temperature": 0.3},
        )
        return agent, gateway

    def _make_spec_artifact(
        self,
        *,
        artifact_id: str = "spec-123",
        version: str = "1",
        text: str = "# SPEC: Test Spec\n## Background / Goal\nTest spec content.",
    ) -> Artifact:
        return Artifact(
            id=artifact_id,
            type="SPEC",
            name="SPEC.md",
            version=version,
            content={"format": "markdown", "text": text},
            created_by="agent-spec",
            created_at=T_AWARE,
            metadata={"template": "spec"},
        )

    def _make_plan_artifact(
        self,
        *,
        artifact_id: str = "plan-123",
        version: str = "1",
        text: str = (
            "# PLAN: Test Plan\n## Linked SPEC\n...\n## Milestones\n"
            "### M1: Test\n- Deliverables: X\n- Acceptance criteria: Y\n- Depends on: none"
        ),
    ) -> Artifact:
        return Artifact(
            id=artifact_id,
            type="PLAN",
            name="PLAN.md",
            version=version,
            content={"format": "markdown", "text": text},
            created_by="agent-plan",
            created_at=T_AWARE,
            metadata={"template": "plan"},
        )

    def _make_request(
        self,
        *,
        spec_artifact: Artifact | None = None,
        plan_artifact: Artifact | None = None,
        feedback: list[ApprovalFeedback] | None = None,
        agent_id: str = "agent-plan",
        metadata: dict[str, Any] | None = None,
        project_context: dict[str, Any] | None = None,
        language: str | None = None,
    ) -> AgentRequest:
        spec_art = spec_artifact or self._make_spec_artifact()

        artifacts = [spec_art]
        if plan_artifact:
            artifacts.append(plan_artifact)

        inp: dict[str, Any] = {}
        if language is not None:
            inp["language"] = language

        ctx: dict[str, Any] = {}
        if project_context is not None:
            ctx["project"] = project_context
        else:
            ctx["project"] = {
                "name": "AuthService",
                "description": "Handles authentication",
                "technology": ["python", "fastapi"],
            }

        return AgentRequest(
            request_id="req-123",
            task_id="task-456",
            project_id="proj-789",
            workflow_id="software-development",
            agent_id=agent_id,
            input=inp,
            context=ctx,
            artifacts=artifacts,
            feedback=feedback or [],
            metadata=metadata if metadata is not None else {"attempt": 1},
        )

    def test_happy_path_plan_creation(self):
        agent, gateway = self._make_agent(
            [self.valid_reply], model="custom-plan-llm", parameters={"temp": 0.1}
        )
        req = self._make_request(language="en")

        val_res = agent.validate(req)
        self.assertTrue(val_res.valid)
        self.assertEqual(val_res.errors, [])

        res = agent.execute(req)
        self.assertEqual(res.status, "SUCCESS")
        self.assertEqual(res.errors, [])
        self.assertEqual(len(res.artifacts), 1)

        # Artifact checks
        art = res.artifacts[0]
        self.assertEqual(art.type, "PLAN")
        self.assertEqual(art.name, "PLAN.md")
        self.assertEqual(art.version, "1")
        self.assertEqual(art.created_by, "agent-plan")
        self.assertEqual(art.created_at, T_AWARE)
        self.assertEqual(art.content, {"format": "markdown", "text": self.valid_reply})
        self.assertEqual(art.metadata["template"], "plan")
        self.assertEqual(art.metadata["model"], "custom-plan-llm")
        self.assertIn("promptTokens", art.metadata["usage"])
        self.assertIn("completionTokens", art.metadata["usage"])
        self.assertEqual(art.metadata["language"], "en")
        self.assertNotIn("revisionOf", art.metadata)
        # Traceability fields
        self.assertEqual(art.metadata["specArtifactId"], "spec-123")
        self.assertEqual(art.metadata["specVersion"], "1")

        # Output checks
        self.assertEqual(
            res.output,
            {
                "summary": "Plan created",
                "artifactId": art.id,
                "version": "1",
            },
        )

        # Event checks
        event_types = [e.event_type for e in res.events]
        self.assertEqual(
            event_types,
            ["AGENT_STARTED", "ARTIFACT_CREATED", "AGENT_COMPLETED"],
        )

        # Whole result schema validation
        validator_for("AgentResult").validate(res.to_contract())

        # Gateway call checks
        self.assertEqual(len(gateway.requests), 1)
        gw_req = gateway.requests[0]
        self.assertEqual(gw_req.model, "custom-plan-llm")
        self.assertEqual(gw_req.parameters, {"temp": 0.1})
        self.assertEqual(gw_req.metadata, {"agentId": "agent-plan", "requestId": "req-123"})
        self.assertEqual(len(gw_req.messages), 2)
        self.assertEqual(gw_req.messages[0].role, "system")
        self.assertEqual(gw_req.messages[1].role, "user")

        # User message fixed sections in order
        user_body = gw_req.messages[1].content
        self.assertIn("## Linked SPEC", user_body)
        self.assertIn("ID: spec-123", user_body)
        self.assertIn("Version: 1", user_body)
        self.assertIn("## Output language\nen", user_body)
        self.assertIn("## Project context\n", user_body)
        self.assertIn("## Template\n", user_body)
        pos_linked = user_body.find("## Linked SPEC")
        pos_lang = user_body.find("## Output language")
        pos_proj = user_body.find("## Project context")
        pos_tpl = user_body.find("## Template")
        self.assertTrue(pos_linked < pos_lang < pos_proj < pos_tpl)

    def test_revision_mode_flow(self):
        agent, gateway = self._make_agent([self.valid_reply])

        prev_plan = self._make_plan_artifact(
            artifact_id="plan-v1",
            version="1",
            text="# PLAN v1 text",
        )
        fb1 = ApprovalFeedback(
            approval_id="app-1",
            reviewer="alice",
            decision="REQUEST_CHANGES",
            comment="Add more milestones",
        )
        fb2 = ApprovalFeedback(
            approval_id="app-1",
            reviewer="bob",
            decision="REJECTED",
            comment="Testing strategy too vague",
        )

        req = self._make_request(
            plan_artifact=prev_plan,
            feedback=[fb1, fb2],
            metadata={"attempt": 2},
        )

        res = agent.execute(req)
        self.assertEqual(res.status, "SUCCESS")
        self.assertEqual(len(res.artifacts), 1)
        art = res.artifacts[0]
        self.assertEqual(art.version, "2")
        self.assertEqual(art.metadata["revisionOf"], "plan-v1")
        self.assertEqual(art.metadata["specArtifactId"], "spec-123")
        self.assertEqual(art.metadata["specVersion"], "1")
        self.assertEqual(res.metrics.revision_count, 1)
        self.assertEqual(res.metrics.attempt, 2)
        self.assertEqual(
            res.output,
            {
                "summary": "Plan revised",
                "artifactId": art.id,
                "version": "2",
            },
        )

        # Gateway request contains previous plan and reviewer comments
        gw_req = gateway.requests[0]
        user_msg = gw_req.messages[1].content
        self.assertIn("## Previous plan (version 1)\n# PLAN v1 text", user_msg)
        self.assertIn("- [REQUEST_CHANGES] alice: Add more milestones", user_msg)
        self.assertIn("- [REJECTED] bob: Testing strategy too vague", user_msg)

        # System message contains revision prompt
        sys_msg = gw_req.messages[0].content
        self.assertIn("reviewer feedback", sys_msg.lower())

    def test_individual_validation_rules(self):
        agent, gateway = self._make_agent([])

        valid_spec = self._make_spec_artifact()
        valid_plan = self._make_plan_artifact()
        valid_feedback = [
            ApprovalFeedback(
                approval_id="app-1",
                reviewer="rev-1",
                decision="REQUEST_CHANGES",
                comment="Fix it",
            )
        ]

        cases = [
            # 1. Zero SPEC artifacts - use empty artifacts list by passing
            # spec_artifact=None and checking. We need to create a request
            # with no SPEC artifact.
            (
                AgentRequest(
                    request_id="req-1",
                    task_id="task-1",
                    project_id="proj-1",
                    workflow_id="software-development",
                    agent_id="agent-plan",
                    input={},
                    context={
                        "project": {
                            "name": "Test",
                            "description": "Test",
                            "technology": ["python"],
                        }
                    },
                    artifacts=[],
                    feedback=[],
                    metadata={"attempt": 1},
                ),
                "artifacts",
            ),
            # 2. Two SPEC artifacts
            (
                AgentRequest(
                    request_id="req-2",
                    task_id="task-2",
                    project_id="proj-2",
                    workflow_id="software-development",
                    agent_id="agent-plan",
                    input={},
                    context={
                        "project": {
                            "name": "Test",
                            "description": "Test",
                            "technology": ["python"],
                        }
                    },
                    artifacts=[valid_spec, valid_spec],
                    feedback=[],
                    metadata={"attempt": 1},
                ),
                "artifacts",
            ),
            # 3. SPEC artifact without text content
            (
                self._make_request(
                    spec_artifact=Artifact(
                        id="spec-1",
                        type="SPEC",
                        name="SPEC.md",
                        version="1",
                        content={"summary": "no text"},
                        created_by="agent-spec",
                        created_at=T_AWARE,
                    )
                ),
                "artifacts[0].content.text",
            ),
            # 4. SPEC artifact bad version: "0"
            (
                self._make_request(
                    spec_artifact=Artifact(
                        id="spec-1",
                        type="SPEC",
                        name="SPEC.md",
                        version="0",
                        content={"text": "text"},
                        created_by="agent-spec",
                        created_at=T_AWARE,
                    )
                ),
                "artifacts[0].version",
            ),
            # 5. SPEC artifact bad version: "v1"
            (
                self._make_request(
                    spec_artifact=Artifact(
                        id="spec-1",
                        type="SPEC",
                        name="SPEC.md",
                        version="v1",
                        content={"text": "text"},
                        created_by="agent-spec",
                        created_at=T_AWARE,
                    )
                ),
                "artifacts[0].version",
            ),
            # 6. SPEC artifact bad version: "1.2"
            (
                self._make_request(
                    spec_artifact=Artifact(
                        id="spec-1",
                        type="SPEC",
                        name="SPEC.md",
                        version="1.2",
                        content={"text": "text"},
                        created_by="agent-spec",
                        created_at=T_AWARE,
                    )
                ),
                "artifacts[0].version",
            ),
            # 7. Two PLAN artifacts
            (
                AgentRequest(
                    request_id="req-7",
                    task_id="task-7",
                    project_id="proj-7",
                    workflow_id="software-development",
                    agent_id="agent-plan",
                    input={},
                    context={
                        "project": {
                            "name": "Test",
                            "description": "Test",
                            "technology": ["python"],
                        }
                    },
                    artifacts=[valid_spec, valid_plan, valid_plan],
                    feedback=[],
                    metadata={"attempt": 1},
                ),
                "artifacts",
            ),
            # 8. PLAN artifact without feedback (revision mode without feedback)
            (
                self._make_request(spec_artifact=valid_spec, plan_artifact=valid_plan, feedback=[]),
                "feedback",
            ),
            # 9. Feedback without PLAN artifact
            (
                self._make_request(spec_artifact=valid_spec, feedback=valid_feedback),
                "artifacts",
            ),
            # 10. PLAN content without text
            (
                self._make_request(
                    spec_artifact=valid_spec,
                    plan_artifact=Artifact(
                        id="plan-1",
                        type="PLAN",
                        name="PLAN.md",
                        version="1",
                        content={"summary": "no text"},
                        created_by="agent-plan",
                        created_at=T_AWARE,
                    ),
                    feedback=valid_feedback,
                ),
                "artifacts[1].content.text",
            ),
            # 11. PLAN artifact bad version: "0"
            (
                self._make_request(
                    spec_artifact=valid_spec,
                    plan_artifact=Artifact(
                        id="plan-1",
                        type="PLAN",
                        name="PLAN.md",
                        version="0",
                        content={"text": "text"},
                        created_by="agent-plan",
                        created_at=T_AWARE,
                    ),
                    feedback=valid_feedback,
                ),
                "artifacts[1].version",
            ),
            # 12. PLAN artifact bad version: "v1"
            (
                self._make_request(
                    spec_artifact=valid_spec,
                    plan_artifact=Artifact(
                        id="plan-1",
                        type="PLAN",
                        name="PLAN.md",
                        version="v1",
                        content={"text": "text"},
                        created_by="agent-plan",
                        created_at=T_AWARE,
                    ),
                    feedback=valid_feedback,
                ),
                "artifacts[1].version",
            ),
            # 13. Unknown artifact type
            (
                AgentRequest(
                    request_id="req-13",
                    task_id="task-13",
                    project_id="proj-13",
                    workflow_id="software-development",
                    agent_id="agent-plan",
                    input={},
                    context={
                        "project": {
                            "name": "Test",
                            "description": "Test",
                            "technology": ["python"],
                        }
                    },
                    artifacts=[
                        valid_spec,
                        Artifact(
                            id="unknown-1",
                            type="UNKNOWN",
                            name="UNKNOWN.md",
                            version="1",
                            content={"text": "text"},
                            created_by="agent-other",
                            created_at=T_AWARE,
                        ),
                    ],
                    feedback=[],
                    metadata={"attempt": 1},
                ),
                "artifacts[1].type",
            ),
            # 14. Non-empty input (PlanAgent expects empty input - requirement must not be present)
            (
                AgentRequest(
                    request_id="req-14",
                    task_id="task-14",
                    project_id="proj-14",
                    workflow_id="software-development",
                    agent_id="agent-plan",
                    input={"requirement": "test"},
                    context={
                        "project": {
                            "name": "Test",
                            "description": "Test",
                            "technology": ["python"],
                        }
                    },
                    artifacts=[valid_spec],
                    feedback=[],
                    metadata={"attempt": 1},
                ),
                "input.requirement",
            ),
            # 15. Bad language (empty string)
            (
                self._make_request(spec_artifact=valid_spec, language=""),
                "input.language",
            ),
            # 16. Bad language (whitespace-only)
            (
                self._make_request(spec_artifact=valid_spec, language="   "),
                "input.language",
            ),
            # 17. Bad attempt: 0
            (
                self._make_request(spec_artifact=valid_spec, metadata={"attempt": 0}),
                "metadata.attempt",
            ),
            # 18. Bad attempt: bool True
            (
                self._make_request(spec_artifact=valid_spec, metadata={"attempt": True}),
                "metadata.attempt",
            ),
            # 19. Bad attempt: string
            (
                self._make_request(spec_artifact=valid_spec, metadata={"attempt": "1"}),
                "metadata.attempt",
            ),
            # 20. Wrong agentId
            (
                self._make_request(spec_artifact=valid_spec, agent_id="other-agent"),
                "agentId",
            ),
        ]

        for req, expected_path in cases:
            with self.subTest(path=expected_path):
                val_res = agent.validate(req)
                self.assertFalse(val_res.valid)
                paths = [err.details.get("path") for err in val_res.errors]
                self.assertIn(
                    expected_path,
                    paths,
                    f"Expected path '{expected_path}' not in {paths}",
                )

                # execute -> REJECTED, gateway never called
                exec_res = agent.execute(req)
                self.assertEqual(exec_res.status, "REJECTED")
                self.assertEqual(len(gateway.requests), 0)

    def test_gateway_failures_map_to_failed_with_retryable(self):
        codes = [
            "LLM_TIMEOUT",
            "LLM_RATE_LIMITED",
            "LLM_INVALID_RESPONSE",
            "INTEGRATION_UNAVAILABLE",
        ]
        for code in codes:
            with self.subTest(code=code):
                gw_err = ModelGatewayError(code, f"Failed with {code}")
                agent, gateway = self._make_agent([gw_err])
                req = self._make_request()

                res = agent.execute(req)
                self.assertEqual(res.status, "FAILED")
                self.assertEqual(res.artifacts, [])
                self.assertEqual(len(res.errors), 1)
                self.assertEqual(res.errors[0].code, code)
                self.assertTrue(res.errors[0].retryable)

                event_types = [e.event_type for e in res.events]
                self.assertEqual(event_types, ["AGENT_STARTED", "AGENT_FAILED"])

    def test_reply_handling_cases(self):
        # 1. Empty reply -> LLM_INVALID_RESPONSE
        agent_empty, _ = self._make_agent(["   \n  "])
        res_empty = agent_empty.execute(self._make_request())
        self.assertEqual(res_empty.status, "FAILED")
        self.assertEqual(res_empty.errors[0].code, "LLM_INVALID_RESPONSE")

        # 2. Reply missing one required section -> missingSections details
        sections_without_one = list(self.template.required_sections)
        missing_sec = sections_without_one.pop(2)  # remove one section
        reply_missing = make_valid_plan_reply(sections_without_one)
        agent_missing, _ = self._make_agent([reply_missing])
        res_missing = agent_missing.execute(self._make_request())
        self.assertEqual(res_missing.status, "FAILED")
        self.assertEqual(res_missing.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertEqual(res_missing.errors[0].details.get("missingSections"), [missing_sec])

        # 3. Reply wrapped in single fenced code block -> unwrapped and accepted
        wrapped_reply = f"```markdown\n{self.valid_reply}\n```"
        agent_wrapped, _ = self._make_agent([wrapped_reply])
        res_wrapped = agent_wrapped.execute(self._make_request())
        self.assertEqual(res_wrapped.status, "SUCCESS")
        self.assertEqual(res_wrapped.artifacts[0].content["text"], self.valid_reply)

        # 4. Reply with different case in heading -> rejected
        reply_diff_case = self.valid_reply.replace(
            "## Scope and out of scope", "## scope and out of scope"
        )
        agent_case, _ = self._make_agent([reply_diff_case])
        res_case = agent_case.execute(self._make_request())
        self.assertEqual(res_case.status, "FAILED")
        self.assertEqual(res_case.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn(
            "## Scope and out of scope",
            res_case.errors[0].details.get("missingSections", []),
        )

        # 5. Reply with duplicate milestone ID -> FAILED with milestoneIssues
        reply_dup_milestone = self.valid_reply.replace(
            "### M2: Core Implementation", "### M1: Duplicate"
        )
        agent_dup, _ = self._make_agent([reply_dup_milestone])
        res_dup = agent_dup.execute(self._make_request())
        self.assertEqual(res_dup.status, "FAILED")
        self.assertEqual(res_dup.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("milestoneIssues", res_dup.errors[0].details)
        self.assertTrue(
            any(
                "Duplicate milestone ID" in issue
                for issue in res_dup.errors[0].details["milestoneIssues"]
            )
        )

        # 6. Reply with missing milestone field -> FAILED with milestoneIssues
        reply_missing_field = self.valid_reply.replace(
            "- Acceptance criteria: All unit tests pass", ""
        )
        agent_missing, _ = self._make_agent([reply_missing_field])
        res_missing = agent_missing.execute(self._make_request())
        self.assertEqual(res_missing.status, "FAILED")
        self.assertEqual(res_missing.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("milestoneIssues", res_missing.errors[0].details)
        self.assertTrue(
            any(
                "missing 'Acceptance criteria' field" in issue
                for issue in res_missing.errors[0].details["milestoneIssues"]
            )
        )

        # 7. Reply with dependency on non-existent milestone -> FAILED with milestoneIssues
        reply_bad_dep = self.valid_reply.replace("- Depends on: M1", "- Depends on: M99")
        agent_bad_dep, _ = self._make_agent([reply_bad_dep])
        res_bad_dep = agent_bad_dep.execute(self._make_request())
        self.assertEqual(res_bad_dep.status, "FAILED")
        self.assertEqual(res_bad_dep.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("milestoneIssues", res_bad_dep.errors[0].details)
        self.assertTrue(
            any(
                "later or non-existent milestone" in issue
                for issue in res_bad_dep.errors[0].details["milestoneIssues"]
            )
        )

    def test_unexpected_gateway_exception_redacted(self):
        agent, _ = self._make_agent([RuntimeError("DATABASE_PASSWORD_SECRET_987")])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "AGENT_EXECUTION_FAILED")
        self.assertEqual(res.errors[0].details, {"exceptionType": "RuntimeError"})
        dumped = json.dumps(res.to_contract())
        self.assertNotIn("DATABASE_PASSWORD_SECRET_987", dumped)

    def test_project_context_whitelisting(self):
        agent, gateway = self._make_agent([self.valid_reply])
        req = self._make_request(
            project_context={
                "name": "PublicProject",
                "description": "Public description",
                "technology": ["python"],
                "api_secret": "TOP_SECRET_API_KEY",
                "internal_token": "SHOULD_NOT_LEAK",
            }
        )
        res = agent.execute(req)
        self.assertEqual(res.status, "SUCCESS")

        user_content = gateway.requests[0].messages[1].content
        self.assertIn("PublicProject", user_content)
        self.assertIn("Public description", user_content)
        self.assertNotIn("TOP_SECRET_API_KEY", user_content)
        self.assertNotIn("SHOULD_NOT_LEAK", user_content)

    def test_determinism_and_immutability(self):
        script = [self.valid_reply]
        agent1, _ = self._make_agent(list(script))
        agent2, _ = self._make_agent(list(script))

        req = self._make_request()
        req_copy = copy.deepcopy(req)

        res1 = agent1.execute(req)
        res2 = agent2.execute(req)

        self.assertEqual(req, req_copy)
        self.assertEqual(res1.to_contract(), res2.to_contract())

    def test_milestone_validation_sequential_ids(self):
        """Test that non-sequential milestone IDs are rejected."""
        reply = self.valid_reply.replace("### M2: Core Implementation", "### M3: Skipped M2")
        agent, _ = self._make_agent([reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("milestoneIssues", res.errors[0].details)
        self.assertTrue(
            any(
                "sequential" in issue
                for issue in res.errors[0].details["milestoneIssues"]
            )
        )

    def test_milestone_validation_no_milestones(self):
        """Test that a plan without milestones is rejected."""
        # Create a reply with all required sections but no milestones (no ### M1: headings)
        lines = ["# PLAN: Test Plan"]
        for sec in self.template.required_sections:
            lines.append(sec)
            lines.append("Section details content.")
        # Note: no milestone content added
        reply = "\n\n".join(lines)

        agent, _ = self._make_agent([reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("milestoneIssues", res.errors[0].details)
        self.assertTrue(
            any(
                "No milestones found" in issue
                for issue in res.errors[0].details["milestoneIssues"]
            )
        )

    def test_linked_spec_references_input_spec(self):
        """Test that the PLAN artifact metadata contains specArtifactId and specVersion."""
        custom_spec = self._make_spec_artifact(
            artifact_id="custom-spec-456",
            version="3",
            text="# SPEC: Custom Spec\n...",
        )
        # Create a valid reply with the custom spec ID and version
        custom_reply = make_valid_plan_reply(
            self.template.required_sections,
            spec_id="custom-spec-456",
            spec_version="3",
        )
        agent, gateway = self._make_agent([custom_reply])
        req = self._make_request(spec_artifact=custom_spec)

        res = agent.execute(req)
        self.assertEqual(res.status, "SUCCESS")
        art = res.artifacts[0]
        self.assertEqual(art.metadata["specArtifactId"], "custom-spec-456")
        self.assertEqual(art.metadata["specVersion"], "3")

        # Also verify the Linked SPEC section in user message
        user_content = gateway.requests[0].messages[1].content
        self.assertIn("ID: custom-spec-456", user_content)
        self.assertIn("Version: 3", user_content)

    def test_milestone_validation_later_milestone_dependency(self):
        """Test that a milestone depending on a later milestone is rejected."""
        # M2 depends on M3 (later milestone)
        reply = self.valid_reply.replace(
            "- Depends on: M1", "- Depends on: M3"
        )
        agent, _ = self._make_agent([reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("milestoneIssues", res.errors[0].details)
        self.assertTrue(
            any(
                "later or non-existent milestone" in issue
                for issue in res.errors[0].details["milestoneIssues"]
            )
        )

    def test_milestone_validation_self_dependency(self):
        """Test that a milestone depending on itself is rejected."""
        # M1 depends on M1
        reply = self.valid_reply.replace(
            "- Depends on: none", "- Depends on: M1"
        )
        agent, _ = self._make_agent([reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("milestoneIssues", res.errors[0].details)
        self.assertTrue(
            any(
                "self-dependency" in issue
                for issue in res.errors[0].details["milestoneIssues"]
            )
        )

    def test_milestone_validation_max_milestones(self):
        """Test that exceeding max milestones is rejected."""
        # Create a reply with 21 milestones (MAX_MILESTONES = 20)
        lines = ["# PLAN: Test Plan"]
        for sec in self.template.required_sections:
            if sec == "## Milestones":
                lines.append(sec)
                for i in range(1, 22):  # M1 through M21
                    lines.append(f"### M{i}: Milestone {i}")
                    lines.append(f"- Deliverables: Deliverable {i}")
                    lines.append(f"- Acceptance criteria: Criteria {i}")
                    lines.append(f"- Depends on: {'none' if i == 1 else f'M{i-1}'}")
            else:
                lines.append(sec)
                lines.append("Section details content.")
        reply = "\n\n".join(lines)

        agent, _ = self._make_agent([reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("milestoneIssues", res.errors[0].details)
        self.assertTrue(
            any(
                "Too many milestones" in issue
                for issue in res.errors[0].details["milestoneIssues"]
            )
        )


    def test_milestone_validation_10_plus_valid_milestones(self):
        """Test that 12 valid milestones (M1..M12) pass validation with numeric ordering."""
        lines = ["# PLAN: Test Plan"]
        for sec in self.template.required_sections:
            lines.append(sec)
            if sec == "## Linked SPEC":
                lines.append("ID: spec-123")
                lines.append("Version: 1")
            elif sec == "## Milestones":
                for i in range(1, 13):  # M1 through M12
                    lines.append(f"### M{i}: Milestone {i}")
                    lines.append(f"- Deliverables: Deliverable {i}")
                    lines.append(f"- Acceptance criteria: Criteria {i}")
                    lines.append(f"- Depends on: {'none' if i == 1 else f'M{i-1}'}")
            else:
                lines.append("Section details content.")
        reply = "\n\n".join(lines)

        agent, _ = self._make_agent([reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "SUCCESS")

        # Also test milestone_ancestors directly on the parsed milestones
        milestones = parse_milestones(reply)
        self.assertEqual(len(milestones), 12)
        # Check numeric ordering: M10 comes after M9, not before
        ids = [m.id for m in milestones]
        self.assertEqual(ids, [f"M{i}" for i in range(1, 13)])
        ancestors = milestone_ancestors(milestones)
        # M12 should have 11 ancestors (M1 through M11)
        self.assertEqual(len(ancestors["M12"]), 11)
        self.assertEqual(ancestors["M1"], frozenset())

    def test_linked_spec_wrong_artifact_id_in_output(self):
        """Test LLM output with wrong SPEC artifact ID in Linked SPEC section."""
        # Valid reply but with wrong SPEC ID in the output
        wrong_reply = self.valid_reply.replace("ID: spec-123", "ID: wrong-spec-999")
        agent, _ = self._make_agent([wrong_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("linkedSpecIssues", res.errors[0].details)
        self.assertTrue(
            any(
                "does not match input SPEC artifact ID" in issue
                for issue in res.errors[0].details["linkedSpecIssues"]
            )
        )

    def test_linked_spec_wrong_version_in_output(self):
        """Test LLM output with wrong SPEC version in Linked SPEC section."""
        wrong_reply = self.valid_reply.replace("Version: 1", "Version: 999")
        agent, _ = self._make_agent([wrong_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("linkedSpecIssues", res.errors[0].details)
        self.assertTrue(
            any(
                "does not match input SPEC artifact version" in issue
                for issue in res.errors[0].details["linkedSpecIssues"]
            )
        )

    def test_linked_spec_missing_reference_in_output(self):
        """Test LLM output with Linked SPEC section header but missing ID/Version lines."""
        # Keep the section header but remove ID and Version lines
        lines = self.valid_reply.splitlines()
        filtered = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("ID:") or stripped.startswith("Version:"):
                continue
            filtered.append(line)
        reply = "\n".join(filtered)

        agent, _ = self._make_agent([reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("linkedSpecIssues", res.errors[0].details)
        self.assertTrue(
            any(
                "missing 'ID:' line" in issue
                for issue in res.errors[0].details["linkedSpecIssues"]
            )
        )
        self.assertTrue(
            any(
                "missing 'Version:' line" in issue
                for issue in res.errors[0].details["linkedSpecIssues"]
            )
        )

    def test_linked_spec_correct_reference_accepted(self):
        """Test that correct Linked SPEC reference in LLM output is accepted."""
        # This is essentially the happy path but focused on linked spec validation
        agent, gateway = self._make_agent([self.valid_reply])
        req = self._make_request(language="en")
        res = agent.execute(req)
        self.assertEqual(res.status, "SUCCESS")
        # Verify the artifact has the traceability fields
        art = res.artifacts[0]
        self.assertEqual(art.metadata["specArtifactId"], "spec-123")
        self.assertEqual(art.metadata["specVersion"], "1")

    def test_linked_spec_validation_unit_regression(self):
        """Regression test: directly call _validate_linked_spec_section to ensure no NameError."""

        spec_art = Artifact(
            id="spec-456",
            type="SPEC",
            name="SPEC.md",
            version="2",
            content={"format": "markdown", "text": "spec content"},
            created_by="agent-spec",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            metadata={},
        )

        # Valid reply with matching ID/version
        valid_reply = """# PLAN: Test
## Linked SPEC
ID: spec-456
Version: 2
## Milestones
### M1: Test
- Deliverables: X
- Acceptance criteria: Y
- Depends on: none"""
        issues = PlanAgent._validate_linked_spec_section(valid_reply, spec_art)
        self.assertEqual(issues, [])

        # Wrong ID
        wrong_id_reply = valid_reply.replace("ID: spec-456", "ID: wrong-id")
        issues = PlanAgent._validate_linked_spec_section(wrong_id_reply, spec_art)
        self.assertEqual(len(issues), 1)
        self.assertIn("does not match input SPEC artifact ID", issues[0])

        # Wrong version
        wrong_ver_reply = valid_reply.replace("Version: 2", "Version: 99")
        issues = PlanAgent._validate_linked_spec_section(wrong_ver_reply, spec_art)
        self.assertEqual(len(issues), 1)
        self.assertIn("does not match input SPEC artifact version", issues[0])

        # Missing section
        no_section_reply = valid_reply.replace("## Linked SPEC\nID: spec-456\nVersion: 2", "")
        issues = PlanAgent._validate_linked_spec_section(no_section_reply, spec_art)
        self.assertEqual(len(issues), 1)
        self.assertIn("Missing '## Linked SPEC' section", issues[0])

        # Missing ID line
        no_id_reply = valid_reply.replace("ID: spec-456", "")
        issues = PlanAgent._validate_linked_spec_section(no_id_reply, spec_art)
        self.assertEqual(len(issues), 1)
        self.assertIn("missing 'ID:' line", issues[0])

        # Missing Version line
        no_ver_reply = valid_reply.replace("Version: 2", "")
        issues = PlanAgent._validate_linked_spec_section(no_ver_reply, spec_art)
        self.assertEqual(len(issues), 1)
        self.assertIn("missing 'Version:' line", issues[0])

    def test_happy_path_plan_artifact_fields(self):
        """Test that happy-path result contains PLAN artifact with all expected fields."""
        agent, gateway = self._make_agent([self.valid_reply])
        req = self._make_request(language="en")
        res = agent.execute(req)

        self.assertEqual(res.status, "SUCCESS")
        self.assertEqual(len(res.artifacts), 1)

        art = res.artifacts[0]
        self.assertEqual(art.type, "PLAN")
        self.assertEqual(art.name, "PLAN.md")
        self.assertEqual(art.version, "1")
        self.assertEqual(art.created_by, "agent-plan")
        self.assertEqual(art.content, {"format": "markdown", "text": self.valid_reply})
        self.assertEqual(art.metadata["template"], "plan")
        self.assertEqual(art.metadata["specArtifactId"], "spec-123")
        self.assertEqual(art.metadata["specVersion"], "1")
        self.assertIn("promptTokens", art.metadata["usage"])
        self.assertIn("completionTokens", art.metadata["usage"])
        self.assertEqual(art.metadata["language"], "en")
        self.assertNotIn("revisionOf", art.metadata)

        # Output structure
        self.assertEqual(
            res.output,
            {
                "summary": "Plan created",
                "artifactId": art.id,
                "version": "1",
            },
        )

    def test_milestone_missing_deliverables_field(self):
        """Test that missing Deliverables field is rejected."""
        reply = self.valid_reply.replace("- Deliverables: Project scaffold", "")
        agent, _ = self._make_agent([reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("milestoneIssues", res.errors[0].details)
        self.assertTrue(
            any(
                "missing 'Deliverables' field" in issue
                for issue in res.errors[0].details["milestoneIssues"]
            )
        )

    def test_milestone_missing_depends_on_field(self):
        """Test that missing Depends on field is rejected."""
        reply = self.valid_reply.replace("- Depends on: none", "")
        agent, _ = self._make_agent([reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("milestoneIssues", res.errors[0].details)
        self.assertTrue(
            any(
                "missing 'Depends on' field" in issue
                for issue in res.errors[0].details["milestoneIssues"]
            )
        )

    def test_size_limit_exceeded(self):
        """Test that SPEC+PLAN content exceeding MAX_PLAN_CHARS is rejected."""
        # Create a SPEC artifact with very large content
        from asf.agents.plan.agent import MAX_PLAN_CHARS
        large_text = "x" * (MAX_PLAN_CHARS + 1)
        spec_art = Artifact(
            id="spec-large",
            type="SPEC",
            name="SPEC.md",
            version="1",
            content={"format": "markdown", "text": large_text},
            created_by="agent-spec",
            created_at=T_AWARE,
            metadata={"template": "spec"},
        )
        req = self._make_request(spec_artifact=spec_art)
        agent, _ = self._make_agent([self.valid_reply])
        val_res = agent.validate(req)
        self.assertFalse(val_res.valid)
        paths = [err.details.get("path") for err in val_res.errors]
        self.assertIn("artifacts", paths)
        self.assertTrue(
            any("exceeds" in err.message for err in val_res.errors)
        )

        # Execute should also be REJECTED
        exec_res = agent.execute(req)
        self.assertEqual(exec_res.status, "REJECTED")

if __name__ == "__main__":
    unittest.main()