"""Agent rule assignments and filesystem-backed rule endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from asf.api.agent_skill_settings import AgentSkillSettings, _agent_type
from asf.api.rule_catalogue import MAX_RULE_BYTES, list_rules, read_rule, rule_path, rule_root


class AgentRuleSettings(AgentSkillSettings):
    def selected(self, agent: str) -> list[str]:
        return self.snapshot().get(agent, [])


class RuleSelection(BaseModel):
    rules: list[str]


class RuleFileUpdate(BaseModel):
    content: str


def _settings(service: Any) -> AgentRuleSettings:
    value = getattr(service, "_agent_rule_settings", None)
    if value is None:
        raise HTTPException(503, "Agent rule settings are unavailable")
    return value


def _register_files(router: APIRouter, root: Path) -> None:
    @router.get("/rules")
    def catalogue() -> list[dict[str, str]]:
        return list_rules(root)

    @router.get("/rules/files/{rule_id:path}")
    def get_file(rule_id: str) -> dict[str, str]:
        try:
            return {"content": read_rule(root, rule_id)}
        except ValueError as error:
            raise HTTPException(404, str(error)) from error

    @router.put("/rules/files/{rule_id:path}")
    def put_file(rule_id: str, body: RuleFileUpdate) -> dict[str, str]:
        try:
            read_rule(root, rule_id)
            path = rule_path(root, rule_id)
            if len(body.content.encode("utf-8")) > MAX_RULE_BYTES:
                raise HTTPException(413, "Rule file is too large")
            path.write_text(body.content, encoding="utf-8")
        except ValueError as error:
            raise HTTPException(404, str(error)) from error
        return {"content": body.content}


def _register_assignments(router: APIRouter, service: Any, root: Path) -> None:
    @router.get("/agents/{agent_id}/rules")
    def get_agent_rules(agent_id: str) -> dict[str, list[str]]:
        return {"rules": _settings(service).selected(_agent_type(service, agent_id, "Rule"))}

    @router.put("/agents/{agent_id}/rules")
    def put_agent_rules(agent_id: str, body: RuleSelection) -> dict[str, list[str]]:
        agent = _agent_type(service, agent_id, "Rule")
        available = {rule["id"] for rule in list_rules(root)}
        if set(body.rules) - available:
            raise HTTPException(422, "One or more rules are not in the catalogue")
        for rule_id in body.rules:
            try:
                read_rule(root, rule_id)
            except ValueError as error:
                raise HTTPException(422, f"Rule '{rule_id}': {error}") from error
        _settings(service).save(agent, body.rules)
        return {"rules": _settings(service).selected(agent)}


def rule_router(service: Any) -> APIRouter:
    root = rule_root(getattr(service, "_projects_dir", None))
    router = APIRouter()
    _register_files(router, root)
    _register_assignments(router, service, root)
    return router
