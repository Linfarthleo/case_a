"""Minimal agent contract and explicit registry (no dynamic plugin loading)."""

from dataclasses import dataclass
from typing import Protocol

from application.budget import ExecutionBudget
from domain.models.document import AgentResponse
from domain.models.permissions import AccessScope


@dataclass(frozen=True)
class AgentRequest:
    query: str


@dataclass(frozen=True)
class AgentContext:
    request_id: str
    access_scope: AccessScope
    budget: ExecutionBudget


class Agent(Protocol):
    async def execute(self, request: AgentRequest, context: AgentContext) -> AgentResponse:
        ...


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}

    def register(self, name: str, agent: Agent) -> None:
        if name in self._agents:
            raise ValueError(f"agent already registered: {name}")
        self._agents[name] = agent

    def get(self, name: str) -> Agent:
        return self._agents[name]
