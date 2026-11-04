from __future__ import annotations

from typing import Protocol

from asf.contracts.models import AgentMetadata, AgentRequest, AgentResult, ValidationResult


class Agent(Protocol):
    def get_metadata(self) -> AgentMetadata: ...

    def validate(self, request: AgentRequest) -> ValidationResult: ...

    def execute(self, request: AgentRequest) -> AgentResult: ...


class AgentRegistry:
    """One explicit implementation per agent type; no ambiguous dispatch."""

    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}
        self._types: dict[str, str] = {}

    def register(self, agent: Agent) -> None:
        metadata = agent.get_metadata()
        if metadata.id in self._agents or metadata.type in self._types:
            raise ValueError("An agent with this ID or type is already registered")
        self._agents[metadata.id] = agent
        self._types[metadata.type] = metadata.id

    def get(self, agent_id: str) -> Agent:
        return self._agents[agent_id]

    def for_type(self, agent_type: str) -> Agent:
        return self.get(self._types[agent_type])

    def list(self) -> list[AgentMetadata]:
        return [agent.get_metadata().model_copy(deep=True) for agent in self._agents.values()]

    def unregister(self, agent_id: str) -> None:
        del self._agents[agent_id]
        self._types = {kind: key for kind, key in self._types.items() if key != agent_id}
