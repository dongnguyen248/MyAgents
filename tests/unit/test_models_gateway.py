from __future__ import annotations

import ast
import unittest
from datetime import UTC, datetime
from pathlib import Path

from asf.contracts.models import ModelMessage, ModelRequest, ModelResponse, ModelUsage
from asf.models.errors import ALLOWED_GATEWAY_ERROR_CODES, ModelGatewayError
from asf.models.fake import ScriptedModelGateway
from asf.models.ports import ModelGateway
from tests.unit.contract_models import validator_for
from tests.unit.purity import assert_pure_package

T_AWARE = datetime(2026, 10, 20, 14, 0, 0, tzinfo=UTC)
T_NAIVE = datetime(2026, 10, 20, 14, 0, 0)


def parse_errors_catalog() -> dict[str, tuple[str, bool]]:
    errors_md = Path(__file__).resolve().parents[2] / "contracts" / "errors.md"
    lines = errors_md.read_text(encoding="utf-8").splitlines()
    catalog: dict[str, tuple[str, bool]] = {}
    for line in lines:
        if line.startswith("|") and not line.startswith("| code") and not line.startswith("|---"):
            parts = [p.strip() for p in line.split("|")[1:-1]]
            if len(parts) >= 3:
                code, category, retryable_str = parts[0], parts[1], parts[2]
                catalog[code] = (category, retryable_str.lower() == "true")
    return catalog


class ModelsGatewayTests(unittest.TestCase):
    def test_protocol_conformance(self):
        # Static type check that ScriptedModelGateway satisfies ModelGateway protocol
        fake = ScriptedModelGateway(["ok"])
        gateway: ModelGateway = fake
        req = ModelRequest(messages=[ModelMessage(role="user", content="hello")])
        res = gateway.complete(req)
        self.assertEqual(res.content, "ok")

    def test_scripted_fake_order_and_exhaustion(self):
        fake = ScriptedModelGateway(["first", "second"])
        req = ModelRequest(messages=[ModelMessage(role="user", content="hello")])

        res1 = fake.complete(req)
        self.assertEqual(res1.content, "first")

        res2 = fake.complete(req)
        self.assertEqual(res2.content, "second")

        with self.assertRaises(RuntimeError) as ctx:
            fake.complete(req)
        self.assertIn("script exhausted", str(ctx.exception))

    def test_scripted_fake_deep_copy_recording(self):
        fake = ScriptedModelGateway(["reply"])
        req = ModelRequest(
            messages=[ModelMessage(role="user", content="original")],
            parameters={"temp": 0.7},
            model="test-model",
            metadata={"run": 1},
        )
        fake.complete(req)

        self.assertEqual(len(fake.requests), 1)
        recorded = fake.requests[0]
        self.assertEqual(recorded.parameters["temp"], 0.7)

        # Mutating recorded does not affect caller's request
        recorded.parameters["temp"] = 999.0
        recorded.metadata["run"] = 999
        self.assertEqual(req.parameters["temp"], 0.7)
        self.assertEqual(req.metadata["run"], 1)

        # Mutating caller's request does not affect recorded
        req.parameters["temp"] = -1.0
        self.assertEqual(fake.requests[0].parameters["temp"], 999.0)

    def test_str_item_deterministic_usage(self):
        fake = ScriptedModelGateway(["three word response"])
        req = ModelRequest(
            messages=[
                ModelMessage(role="system", content="you are helpful"),  # 3 words
                ModelMessage(role="user", content="hello there friend"),  # 3 words
            ],
            model="custom-llm",
        )
        res = fake.complete(req)
        self.assertEqual(res.model, "custom-llm")
        self.assertEqual(res.usage.prompt_tokens, 6)
        self.assertEqual(res.usage.completion_tokens, 3)
        self.assertEqual(res.finish_reason, "stop")

    def test_default_model_name_when_none(self):
        fake = ScriptedModelGateway(["ok"])
        req = ModelRequest(
            messages=[ModelMessage(role="user", content="hi")],
            model=None,
        )
        res = fake.complete(req)
        self.assertEqual(res.model, "scripted-model")

    def test_model_response_item_returned_directly(self):
        expected_res = ModelResponse(
            content="pre-built",
            model="explicit-model",
            usage=ModelUsage(prompt_tokens=1, completion_tokens=1),
            finish_reason="stop",
            metadata={"custom": True},
        )
        fake = ScriptedModelGateway([expected_res])
        req = ModelRequest(messages=[ModelMessage(role="user", content="hi")])
        res = fake.complete(req)
        self.assertIs(res, expected_res)

    def test_exception_and_gateway_error_raised(self):
        err = ModelGatewayError("LLM_TIMEOUT", "Timed out")
        exc = ValueError("bad parameter")
        fake = ScriptedModelGateway([err, exc])
        req = ModelRequest(messages=[ModelMessage(role="user", content="hi")])

        with self.assertRaises(ModelGatewayError) as ctx1:
            fake.complete(req)
        self.assertIs(ctx1.exception, err)

        with self.assertRaises(ValueError) as ctx2:
            fake.complete(req)
        self.assertIs(ctx2.exception, exc)

    def test_model_gateway_error_catalog_codes_and_validation(self):
        catalog = parse_errors_catalog()
        expected_codes = {
            "LLM_TIMEOUT",
            "LLM_RATE_LIMITED",
            "LLM_INVALID_RESPONSE",
            "LLM_AUTH_FAILED",
            "LLM_CONTEXT_TOO_LONG",
            "LLM_BAD_REQUEST",
            "LLM_MODEL_NOT_SUPPORTED",
            "LLM_OUTPUT_TRUNCATED",
            "INTEGRATION_UNAVAILABLE",
        }
        self.assertEqual(set(ALLOWED_GATEWAY_ERROR_CODES.keys()), expected_codes)

        for code in expected_codes:
            with self.subTest(code=code):
                cat_category, cat_retryable = catalog[code]
                err = ModelGatewayError(code, f"Error for {code}", details={"key": "val"})
                self.assertEqual(err.category, cat_category)
                self.assertEqual(err.retryable, cat_retryable)

                # to_platform_error validates against $defs/PlatformError
                p_err = err.to_platform_error(T_AWARE)
                validator_for("PlatformError").validate(p_err)
                self.assertEqual(p_err["code"], code)
                self.assertEqual(p_err["category"], cat_category)
                self.assertEqual(p_err["retryable"], cat_retryable)
                self.assertEqual(p_err["details"], {"key": "val"})

    def test_model_gateway_error_unknown_code_and_naive_now(self):
        with self.assertRaises(ValueError):
            ModelGatewayError("UNKNOWN_CODE", "Error message")

        err = ModelGatewayError("LLM_TIMEOUT", "Timeout")
        with self.assertRaises(ValueError):
            err.to_platform_error(T_NAIVE)

        with self.assertRaises(TypeError):
            err.to_platform_error("not-a-datetime")  # type: ignore[arg-type]

    def test_models_boundary_and_purity(self):
        models_dir = Path(__file__).resolve().parents[2] / "src" / "asf" / "models"

        # Purity check on ports.py and errors.py (strict)
        assert_pure_package(self, models_dir, include=["ports.py", "errors.py"])

        # Purity check on fake.py (no network/subprocess/clock/uuid/random)
        assert_pure_package(self, models_dir, include=["fake.py"])

        # Import boundary check: asf.models may import only asf.contracts and asf.models
        allowed_asf_modules = {
            "asf.contracts",
            "asf.contracts.models",
            "asf.models",
            "asf.models.errors",
            "asf.models.fake",
            "asf.models.limited",
            "asf.models.ports",
        }

        for py_file in models_dir.rglob("*.py"):
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith("asf."):
                            self.assertIn(
                                alias.name,
                                allowed_asf_modules,
                                f"Forbidden import '{alias.name}' in {py_file.name}",
                            )
                elif (
                    isinstance(node, ast.ImportFrom)
                    and node.level == 0
                    and node.module
                    and node.module.startswith("asf.")
                ):
                    self.assertIn(
                        node.module,
                        allowed_asf_modules,
                        f"Forbidden import from '{node.module}' in {py_file.name}",
                    )
