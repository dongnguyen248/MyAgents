from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import get_args

from jsonschema import Draft202012Validator, FormatChecker

from asf.contracts.models import ContractModel

SCHEMA_PATH = (
    Path(__file__).resolve().parents[2] / "contracts" / "schemas" / "contracts.schema.json"
)
with SCHEMA_PATH.open(encoding="utf-8") as schema_file:
    SCHEMA = json.load(schema_file)


def validator_for(definition: str) -> Draft202012Validator:
    defs = dict(SCHEMA["$defs"])
    if definition not in defs:
        if definition == "ModelMessage":
            msg_items = SCHEMA["$defs"]["ModelRequest"]["properties"]["messages"]["items"]
            defs["ModelMessage"] = msg_items
        elif definition == "ModelUsage":
            defs["ModelUsage"] = SCHEMA["$defs"]["ModelResponse"]["properties"]["usage"]
    wrapped_schema = {
        "$schema": SCHEMA["$schema"],
        "$defs": defs,
        "$ref": f"#/$defs/{definition}",
    }
    return Draft202012Validator(wrapped_schema, format_checker=FormatChecker())


def assert_contract_binding(
    test_case: unittest.TestCase,
    model_cls: type[ContractModel],
    def_name: str,
    sample_instance: ContractModel,
    *,
    enum_paths: dict[str, list[str] | str] | None = None,
) -> None:
    """Asserts that a Pydantic contract model conforms to the JSON Schema contract.

    (a) The set of serialized property names equals the schema's property names.
    (b) Every schema-required property is serialized by sample_instance.to_contract().
    (c) Literal values equal the schema enums.
    (d) sample_instance.to_contract() validates against the $def.
    """
    if def_name in SCHEMA["$defs"]:
        schema_def = SCHEMA["$defs"][def_name]
    elif def_name == "ModelMessage":
        schema_def = SCHEMA["$defs"]["ModelRequest"]["properties"]["messages"]["items"]
    elif def_name == "ModelUsage":
        schema_def = SCHEMA["$defs"]["ModelResponse"]["properties"]["usage"]
    else:
        raise KeyError(f"Unknown $def '{def_name}'")

    # (a) Serialized property names match schema properties
    schema_props = set(schema_def.get("properties", {}).keys())
    model_props = set(
        model_cls.model_json_schema(by_alias=True).get("properties", {}).keys()
    )
    test_case.assertEqual(
        model_props,
        schema_props,
        f"Property names mismatch for {def_name}",
    )

    # (b) Every schema-required property is serialized by sample_instance.to_contract()
    contract_data = sample_instance.to_contract()
    for req_prop in schema_def.get("required", []):
        test_case.assertIn(
            req_prop,
            contract_data,
            f"Required property '{req_prop}' missing in to_contract() of {def_name}",
        )

    # (c) Literal values equal schema enums
    if enum_paths:
        for field_name, expected_enum_or_ref in enum_paths.items():
            field_info = model_cls.model_fields[field_name]
            literal_vals = set(get_args(field_info.annotation))
            if isinstance(expected_enum_or_ref, list):
                expected_vals = set(expected_enum_or_ref)
            elif expected_enum_or_ref.startswith("#/$defs/"):
                ref_key = expected_enum_or_ref.split("/")[-1]
                expected_vals = set(SCHEMA["$defs"][ref_key]["enum"])
            elif expected_enum_or_ref in SCHEMA["$defs"]:
                expected_vals = set(SCHEMA["$defs"][expected_enum_or_ref]["enum"])
            elif expected_enum_or_ref in schema_def.get("properties", {}):
                prop = schema_def["properties"][expected_enum_or_ref]
                if "enum" in prop:
                    expected_vals = set(prop["enum"])
                elif "$ref" in prop:
                    ref_key = prop["$ref"].split("/")[-1]
                    expected_vals = set(SCHEMA["$defs"][ref_key]["enum"])
                else:
                    raise KeyError(f"No enum found for {expected_enum_or_ref}")
            else:
                cur = schema_def
                for part in expected_enum_or_ref.strip("/").split("/"):
                    cur = cur[part]
                expected_vals = (
                    set(cur["enum"]) if isinstance(cur, dict) and "enum" in cur else set(cur)
                )
            test_case.assertEqual(
                literal_vals,
                expected_vals,
                f"Enum mismatch for field '{field_name}' in {def_name}",
            )

    # (d) Validates against $def
    defs = dict(SCHEMA["$defs"])
    if def_name not in defs:
        defs[def_name] = schema_def
    wrapped_schema = {
        "$schema": SCHEMA["$schema"],
        "$defs": defs,
        "$ref": f"#/$defs/{def_name}",
    }
    validator = Draft202012Validator(wrapped_schema, format_checker=FormatChecker())
    validator.validate(contract_data)
