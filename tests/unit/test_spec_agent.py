from __future__ import annotations

import copy
import json
import unittest
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from asf.agents.base import AgentRuntime
from asf.agents.loading import load_spec_prompts, load_spec_template
from asf.agents.spec.agent import MAX_REQUIREMENT_CHARS, SpecAgent, SpecSettings
from asf.contracts.models import (
    AgentRequest,
    ApprovalFeedback,
    Artifact,
)
from asf.models.errors import ModelGatewayError
from asf.models.fake import ScriptedModelGateway
from tests.unit.contract_models import validator_for

REPO_ROOT = Path(__file__).resolve().parents[2]
T_AWARE = datetime(2026, 10, 20, 14, 0, 0, tzinfo=UTC)


def counter_id(prefix: str = "id-"):
    count = 0

    def _next() -> str:
        nonlocal count
        count += 1
        return f"{prefix}{count}"

    return _next


def make_valid_reply(template_sections: list[str]) -> str:
    lines = ["# SPEC: Test Specification"]
    for sec in template_sections:
        lines.append(sec)
        lines.append("Section details content.")
    return "\n\n".join(lines)


class SpecAgentTests(unittest.TestCase):
    def setUp(self):
        self.prompts = load_spec_prompts()
        self.template = load_spec_template(REPO_ROOT / "templates")
        self.valid_reply = make_valid_reply(self.template.required_sections)

    def _make_agent(
        self,
        script: list[Any],
        *,
        model: str | None = "test-model",
        parameters: dict[str, Any] | None = None,
        clock=None,
        new_id=None,
    ) -> tuple[SpecAgent, ScriptedModelGateway]:
        gateway = ScriptedModelGateway(script)
        clk = clock or (lambda: T_AWARE)
        nid = new_id or counter_id("gen-")
        runtime = AgentRuntime(models=gateway, clock=clk, new_id=nid)
        agent = SpecAgent(
            runtime,
            SpecSettings(
                prompts=self.prompts,
                template=self.template,
                model=model,
                parameters=parameters or {"temperature": 0.3},
            ),
        )
        return agent, gateway

    def _make_request(
        self,
        *,
        requirement: Any = "Build user authentication service",
        language: Any = None,
        artifacts: list[Artifact] | None = None,
        feedback: list[ApprovalFeedback] | None = None,
        agent_id: str = "agent-spec",
        metadata: dict[str, Any] | None = None,
        project_context: dict[str, Any] | None = None,
    ) -> AgentRequest:
        inp: dict[str, Any] = {}
        if requirement is not ...:
            inp["requirement"] = requirement
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
            artifacts=artifacts or [],
            feedback=feedback or [],
            metadata=metadata if metadata is not None else {"attempt": 1},
        )

    def test_enabled_skills_reach_the_system_prompt(self):
        # Skills resolved into the project context are appended for
        # the agents they apply to (general + security for spec) and
        # withheld from the ones they do not (git).
        agent, gateway = self._make_agent([self.valid_reply])
        project = {
            "name": "AuthService",
            "description": "Handles authentication",
            "technology": ["python", "fastapi"],
            "skills": [
                {"id": "general", "content": "GENERAL SKILL BODY"},
                {"id": "security", "content": "SECURITY SKILL BODY"},
                {"id": "git", "content": "GIT SKILL BODY"},
            ],
        }
        res = agent.execute(self._make_request(project_context=project))
        self.assertEqual(res.status, "SUCCESS")
        system = gateway.requests[0].messages[0].content
        self.assertIn("GENERAL SKILL BODY", system)
        self.assertIn("SECURITY SKILL BODY", system)
        self.assertNotIn("GIT SKILL BODY", system)

    def test_model_request_carries_the_runs_model_tier(self):
        # A complex run's tier (recorded in the run context by the
        # service) must reach the routing gateway via request metadata;
        # a standard run carries no tier key at all.
        agent, gateway = self._make_agent([self.valid_reply])
        req = self._make_request()
        req = req.model_copy(
            update={
                "context": {**req.context, "modelTier": "complex"},
            }
        )
        res = agent.execute(req)
        self.assertEqual(res.status, "SUCCESS")
        self.assertEqual(gateway.requests[0].metadata.get("modelTier"), "complex")

        agent, gateway = self._make_agent([self.valid_reply])
        res = agent.execute(self._make_request())
        self.assertEqual(res.status, "SUCCESS")
        self.assertNotIn("modelTier", gateway.requests[0].metadata)

    def test_happy_path_specification_creation(self):
        agent, gateway = self._make_agent(
            [self.valid_reply], model="custom-spec-llm", parameters={"temp": 0.1}
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
        self.assertEqual(art.type, "SPEC")
        self.assertEqual(art.name, "SPEC.md")
        self.assertEqual(art.version, "1")
        self.assertEqual(art.created_by, "agent-spec")
        self.assertEqual(art.created_at, T_AWARE)
        self.assertEqual(art.content, {"format": "markdown", "text": self.valid_reply})
        self.assertEqual(art.metadata["template"], "spec")
        self.assertEqual(art.metadata["model"], "custom-spec-llm")
        self.assertIn("promptTokens", art.metadata["usage"])
        self.assertIn("completionTokens", art.metadata["usage"])
        self.assertEqual(art.metadata["language"], "en")
        self.assertNotIn("revisionOf", art.metadata)

        # Output checks
        self.assertEqual(
            res.output,
            {
                "summary": "Specification created",
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
        self.assertEqual(gw_req.model, "custom-spec-llm")
        self.assertEqual(gw_req.parameters, {"temp": 0.1})
        self.assertEqual(gw_req.metadata["agentId"], "agent-spec")
        self.assertEqual(gw_req.metadata["requestId"], "req-123")
        self.assertEqual(gw_req.metadata["cachePrefixMessages"], 1)
        self.assertEqual(len(gw_req.messages), 2)
        self.assertEqual(gw_req.messages[0].role, "system")
        self.assertEqual(gw_req.messages[1].role, "user")

        # Requirement must NEVER appear in system message
        self.assertNotIn("Build user authentication service", gw_req.messages[0].content)

        # User message fixed sections in order
        user_body = gw_req.messages[1].content
        self.assertIn("## Requirement\nBuild user authentication service", user_body)
        self.assertIn("## Output language\nen", user_body)
        self.assertIn("## Project context\n", user_body)
        self.assertIn("## Template\n", user_body)
        pos_req = user_body.find("## Requirement")
        pos_lang = user_body.find("## Output language")
        pos_proj = user_body.find("## Project context")
        pos_tpl = user_body.find("## Template")
        self.assertTrue(pos_req < pos_lang < pos_proj < pos_tpl)

    def test_revision_mode_flow(self):
        agent, gateway = self._make_agent([self.valid_reply])

        prev_art = Artifact(
            id="art-v1",
            type="SPEC",
            name="SPEC.md",
            version="1",
            content={"format": "markdown", "text": "# SPEC v1 text"},
            created_by="agent-spec",
            created_at=T_AWARE,
            metadata={"template": "spec"},
        )
        fb1 = ApprovalFeedback(
            approval_id="app-1",
            reviewer="alice",
            decision="REQUEST_CHANGES",
            comment="Add rate limiting to scope",
        )
        fb2 = ApprovalFeedback(
            approval_id="app-1",
            reviewer="bob",
            decision="REJECTED",
            comment="Acceptance criteria too vague",
        )

        req = self._make_request(
            artifacts=[prev_art],
            feedback=[fb1, fb2],
            metadata={"attempt": 2},
        )

        res = agent.execute(req)
        self.assertEqual(res.status, "SUCCESS")
        self.assertEqual(len(res.artifacts), 1)
        art = res.artifacts[0]
        self.assertEqual(art.version, "2")
        self.assertEqual(art.metadata["revisionOf"], "art-v1")
        self.assertEqual(res.metrics.revision_count, 1)
        self.assertEqual(res.metrics.attempt, 2)
        self.assertEqual(
            res.output,
            {
                "summary": "Specification revised",
                "artifactId": art.id,
                "version": "2",
            },
        )

        # Gateway request contains previous spec and reviewer comments
        gw_req = gateway.requests[0]
        user_msg = gw_req.messages[1].content
        self.assertIn("## Previous specification (version 1)\n# SPEC v1 text", user_msg)
        self.assertIn("- [REQUEST_CHANGES] alice: Add rate limiting to scope", user_msg)
        self.assertIn("- [REJECTED] bob: Acceptance criteria too vague", user_msg)

        # System message contains revision prompt
        sys_msg = gw_req.messages[0].content
        self.assertIn("reviewer feedback", sys_msg)

    def test_individual_validation_rules(self):
        agent, gateway = self._make_agent([])

        valid_prev_spec = Artifact(
            id="art-1",
            type="SPEC",
            name="SPEC.md",
            version="1",
            content={"text": "existing spec text"},
            created_by="agent-spec",
            created_at=T_AWARE,
        )
        valid_feedback = [
            ApprovalFeedback(
                approval_id="app-1",
                reviewer="rev-1",
                decision="REQUEST_CHANGES",
                comment="Fix it",
            )
        ]

        cases = [
            # 1. Missing requirement
            (
                self._make_request(requirement=...),
                "input.requirement",
            ),
            # 2. Non-string requirement
            (
                self._make_request(requirement=12345),
                "input.requirement",
            ),
            # 3. Empty requirement
            (
                self._make_request(requirement=""),
                "input.requirement",
            ),
            # 4. Whitespace-only requirement
            (
                self._make_request(requirement="   \n\t  "),
                "input.requirement",
            ),
            # 5. Too-long requirement (> 20000 chars)
            (
                self._make_request(requirement="A" * (MAX_REQUIREMENT_CHARS + 1)),
                "input.requirement",
            ),
            # 6. Bad language (empty string)
            (
                self._make_request(language=""),
                "input.language",
            ),
            # 7. Bad language (whitespace-only)
            (
                self._make_request(language="   "),
                "input.language",
            ),
            # 8. Two SPEC artifacts
            (
                self._make_request(artifacts=[valid_prev_spec, valid_prev_spec]),
                "artifacts",
            ),
            # 9. Feedback without SPEC artifact
            (
                self._make_request(feedback=valid_feedback, artifacts=[]),
                "artifacts",
            ),
            # 10. SPEC artifact without feedback
            (
                self._make_request(artifacts=[valid_prev_spec], feedback=[]),
                "feedback",
            ),
            # 11. SPEC content without text (not dict or empty text)
            (
                self._make_request(
                    artifacts=[
                        Artifact(
                            id="art-1",
                            type="SPEC",
                            name="SPEC.md",
                            version="1",
                            content={"summary": "no text"},
                            created_by="agent-spec",
                            created_at=T_AWARE,
                        )
                    ],
                    feedback=valid_feedback,
                ),
                "artifacts[0].content.text",
            ),
            # 12. SPEC artifact bad version: "0"
            (
                self._make_request(
                    artifacts=[
                        Artifact(
                            id="art-1",
                            type="SPEC",
                            name="SPEC.md",
                            version="0",
                            content={"text": "text"},
                            created_by="agent-spec",
                            created_at=T_AWARE,
                        )
                    ],
                    feedback=valid_feedback,
                ),
                "artifacts[0].version",
            ),
            # 13. SPEC artifact bad version: "v1"
            (
                self._make_request(
                    artifacts=[
                        Artifact(
                            id="art-1",
                            type="SPEC",
                            name="SPEC.md",
                            version="v1",
                            content={"text": "text"},
                            created_by="agent-spec",
                            created_at=T_AWARE,
                        )
                    ],
                    feedback=valid_feedback,
                ),
                "artifacts[0].version",
            ),
            # 14. SPEC artifact bad version: "1.2"
            (
                self._make_request(
                    artifacts=[
                        Artifact(
                            id="art-1",
                            type="SPEC",
                            name="SPEC.md",
                            version="1.2",
                            content={"text": "text"},
                            created_by="agent-spec",
                            created_at=T_AWARE,
                        )
                    ],
                    feedback=valid_feedback,
                ),
                "artifacts[0].version",
            ),
            # 15. Bad attempt: 0
            (
                self._make_request(metadata={"attempt": 0}),
                "metadata.attempt",
            ),
            # 16. Bad attempt: bool True
            (
                self._make_request(metadata={"attempt": True}),
                "metadata.attempt",
            ),
            # 17. Bad attempt: string
            (
                self._make_request(metadata={"attempt": "1"}),
                "metadata.attempt",
            ),
            # 18. Wrong agentId
            (
                self._make_request(agent_id="other-agent"),
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
        reply_missing = make_valid_reply(sections_without_one)
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
        reply_diff_case = self.valid_reply.replace("## Background / Goal", "## background / goal")
        agent_case, _ = self._make_agent([reply_diff_case])
        res_case = agent_case.execute(self._make_request())
        self.assertEqual(res_case.status, "FAILED")
        self.assertEqual(res_case.errors[0].code, "LLM_INVALID_RESPONSE")
        self.assertIn("## Background / Goal", res_case.errors[0].details.get("missingSections", []))

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
