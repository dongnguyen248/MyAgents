"""Dashboard view of project rule configuration."""

from collections.abc import Mapping
from typing import Any


def project_rule_fields(configuration: Any, enabled: Any) -> dict[str, Any]:
    review = configuration.get("review") if isinstance(configuration, Mapping) else None
    files = review.get("rulesFiles") if isinstance(review, Mapping) else None
    inline = review.get("rules") if isinstance(review, Mapping) else None
    return {
        "enabledRules": _strings(enabled),
        "legacyRuleFiles": _strings(files),
        "hasInlineRules": bool(isinstance(inline, str) and inline.strip()),
    }


def _strings(value: Any) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def project_rule_view(profile: Mapping[str, Any]) -> dict[str, Any]:
    keys = ("enabledSkills", "enabledRules", "legacyRuleFiles", "hasInlineRules")
    return {key: profile[key] for key in keys}


def project_rule_fields_from_data(configuration: Any, data: Mapping[str, Any]) -> dict[str, Any]:
    return project_rule_fields(configuration, data.get("enabledRules", data.get("enabled_rules")))
