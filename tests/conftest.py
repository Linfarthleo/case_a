from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from adapters.mcp.simulated_mcp import SimulatedMcpAdapter
from container import Container, build_container
from core.config import Settings
from domain.models.audit import AuditEvent, AuditEventType
from domain.models.tool import ToolCall, ToolExecutionResult
from main import create_app
from observability.metrics import MetricsRegistry
from ports.llm import LLMConfig, LLMResponse, LLMUsage, Message

AUTH_E001 = {"Authorization": "Bearer employee-E001"}
VALID_BODY = {
    "employee_id": "E001",
    "role": "comercial",
    "area": "creditos",
    "query": "¿Cuáles son las condiciones actuales para crédito empresarial?",
}


class InMemoryAudit:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def record(self, event: AuditEvent) -> None:
        self.events.append(event)

    def types(self) -> list[AuditEventType]:
        return [e.type for e in self.events]

    def of(self, event_type: AuditEventType) -> list[AuditEvent]:
        return [e for e in self.events if e.type == event_type]


class SpyMcp:
    """Wraps the simulated MCP (or a scripted outcome) and records every call."""

    def __init__(self, documents: list[dict[str, Any]] | None = None,
                 raw_result: ToolExecutionResult | None = None,
                 errors: list[Exception] | None = None) -> None:
        self._inner = SimulatedMcpAdapter(documents=documents)
        self._raw_result = raw_result
        self._errors = list(errors or [])
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolExecutionResult:
        self.calls.append((name, arguments))
        if self._errors:
            raise self._errors.pop(0)
        if self._raw_result is not None:
            return self._raw_result
        return await self._inner.call_tool(name, arguments)


class ScriptedLLM:
    """Returns scripted responses/exceptions in order; records every invocation."""

    def __init__(self, script: list[LLMResponse | Exception | Callable[..., Any]]) -> None:
        self._script = list(script)
        self.calls: list[dict[str, Any]] = []

    async def generate(self, messages: list[Message], tools=None,
                       config: LLMConfig | None = None) -> LLMResponse:
        self.calls.append({"messages": messages, "tools": tools, "config": config})
        step = self._script.pop(0)
        if isinstance(step, Exception):
            raise step
        if callable(step):
            return await step(messages, tools, config)
        return step


def tool_call(name: str = "mcp_search_documents", **arguments: Any) -> LLMResponse:
    return LLMResponse(tool_calls=(ToolCall(id="c1", name=name, arguments=arguments or {"query": "q"}),),
                       usage=LLMUsage(input_tokens=50, output_tokens=10))


def answer(text: str) -> LLMResponse:
    return LLMResponse(content=text, usage=LLMUsage(input_tokens=200, output_tokens=40))


def make_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = dict(
        app_env="test", otel_enabled=False, retry_base_delay_ms=0, retry_max_delay_ms=0,
        llm_provider="mock", llm_fallback_model=None,
    )
    base.update(overrides)
    return Settings(_env_file=None, **base)


class Harness:
    def __init__(self, settings: Settings, **adapters: Any) -> None:
        self.audit = InMemoryAudit()
        self.metrics = MetricsRegistry()
        self.container: Container = build_container(
            settings, audit=self.audit, metrics=self.metrics, **adapters
        )
        self.client = TestClient(create_app(settings, container=self.container))

    def query(self, body: dict[str, Any] | None = None,
              headers: dict[str, str] | None = AUTH_E001, **changes: Any):
        payload = {**VALID_BODY, **(body or {}), **changes}
        return self.client.post("/api/v1/docs/query", json=payload, headers=headers or {})


@pytest.fixture
def harness_factory() -> Callable[..., Harness]:
    def factory(settings: Settings | None = None, **adapters: Any) -> Harness:
        return Harness(settings or make_settings(), **adapters)

    return factory
