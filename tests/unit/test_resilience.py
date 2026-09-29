"""Spec tests 9, 10, 11 plus timeouts, fallback model, budget and circuit breaker."""

import asyncio

import pytest

from adapters.mcp.resilient_mcp import ResilientMcpClient
from application.budget import BudgetLimits, ExecutionBudget
from application.llm_gateway import LLMGateway
from conftest import ScriptedLLM, SpyMcp, answer, make_settings, tool_call
from core.resilience import CircuitBreaker
from domain.exceptions import (
    BudgetExceededError,
    DependencyTimeoutError,
    DependencyUnavailableError,
    InvalidDependencyResponseError,
    RateLimitedError,
)
from observability.metrics import MetricsRegistry
from observability.tracing import Telemetry

MESSAGES = [{"role": "system", "content": "s"}, {"role": "user", "content": "q"}]


def rate_limited() -> RateLimitedError:
    return RateLimitedError("429", status_code=429)


def gateway(provider, **overrides):
    settings = make_settings(**overrides)
    metrics = MetricsRegistry()
    gw = LLMGateway(provider, settings, Telemetry(metrics, enabled=False),
                    CircuitBreaker("llm", 100, 30))
    return gw, ExecutionBudget(BudgetLimits.from_settings(settings)), metrics


# --- Test 9: bounded LLM retries ---------------------------------------------------
async def test_llm_429_429_200_with_max_retries_1_makes_exactly_two_attempts():
    provider = ScriptedLLM([rate_limited(), rate_limited(), answer("ok")])
    gw, budget, metrics = gateway(provider, llm_max_retries=1)

    with pytest.raises(RateLimitedError):
        await gw.generate(MESSAGES, budget)

    assert len(provider.calls) == 2
    assert metrics.total("llm_retries_total") == 1


async def test_llm_transient_error_then_success():
    provider = ScriptedLLM([rate_limited(), answer("ok")])
    gw, budget, _ = gateway(provider, llm_max_retries=1)
    assert (await gw.generate(MESSAGES, budget)).content == "ok"
    assert budget.llm_calls == 2 and budget.llm_retries == 1


async def test_llm_non_transient_error_is_not_retried():
    provider = ScriptedLLM([InvalidDependencyResponseError("400", status_code=400), answer("ok")])
    gw, budget, _ = gateway(provider, llm_max_retries=3)
    with pytest.raises(InvalidDependencyResponseError):
        await gw.generate(MESSAGES, budget)
    assert len(provider.calls) == 1


async def test_llm_timeout_is_enforced_and_retried_once():
    async def slow(*_):
        await asyncio.sleep(1)

    provider = ScriptedLLM([slow, slow])
    gw, budget, _ = gateway(provider, llm_timeout_ms=20, llm_max_retries=1)
    with pytest.raises(DependencyTimeoutError):
        await gw.generate(MESSAGES, budget)
    assert len(provider.calls) == 2


async def test_request_level_retry_budget_stops_retries():
    provider = ScriptedLLM([rate_limited(), answer("ok")])
    gw, budget, _ = gateway(provider, llm_max_retries=1, max_llm_retries_per_request=0)
    with pytest.raises(BudgetExceededError):
        await gw.generate(MESSAGES, budget)
    assert len(provider.calls) == 1


async def test_fallback_model_used_only_for_transient_errors():
    provider = ScriptedLLM([rate_limited(), answer("from fallback")])
    gw, budget, _ = gateway(provider, llm_max_retries=0, llm_fallback_model="small-model")
    result = await gw.generate(MESSAGES, budget)
    assert result.content == "from fallback"
    assert [c["config"].model for c in provider.calls] == ["mock-model-v1", "small-model"]


async def test_fallback_model_not_used_for_non_transient_errors():
    provider = ScriptedLLM([InvalidDependencyResponseError("401", status_code=401), answer("x")])
    gw, budget, _ = gateway(provider, llm_max_retries=0, llm_fallback_model="small-model")
    with pytest.raises(InvalidDependencyResponseError):
        await gw.generate(MESSAGES, budget)
    assert len(provider.calls) == 1


# --- Test 10: security failures are never retried ---------------------------------------
def test_tool_denied_is_not_retried(harness_factory):
    llm = ScriptedLLM([tool_call("get_employee_permissions")] * 3)
    mcp = SpyMcp()
    h = harness_factory(make_settings(llm_max_retries=2, mcp_max_retries=2),
                        llm_provider=llm, mcp=mcp)

    assert h.query().status_code == 403
    assert len(llm.calls) == 1
    assert h.metrics.total("llm_retries_total") == 0
    assert h.metrics.total("mcp_retries_total") == 0
    assert mcp.calls == []


# --- Test 11: call budget ---------------------------------------------------------------
async def test_llm_call_budget_blocks_before_calling_provider():
    provider = ScriptedLLM([answer("1"), answer("2")])
    gw, budget, _ = gateway(provider, max_llm_calls_per_request=1)

    await gw.generate(MESSAGES, budget)
    with pytest.raises(BudgetExceededError):
        await gw.generate(MESSAGES, budget)
    assert len(provider.calls) == 1


def test_agent_stops_when_llm_call_budget_is_exhausted(harness_factory):
    llm = ScriptedLLM([tool_call(), answer("never used [DOC-001]")])
    h = harness_factory(make_settings(max_llm_calls_per_request=1), llm_provider=llm)

    response = h.query()

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "budget_exceeded"
    assert len(llm.calls) == 1
    assert h.metrics.total("budget_exceeded_total") == 1


async def test_cost_budget_blocks_before_calling_provider():
    provider = ScriptedLLM([answer("x")])
    gw, budget, _ = gateway(provider, max_estimated_cost_usd=0.0000001)
    with pytest.raises(BudgetExceededError):
        await gw.generate(MESSAGES, budget)
    assert provider.calls == []


async def test_input_token_budget_blocks_before_calling_provider():
    provider = ScriptedLLM([answer("x")])
    gw, budget, _ = gateway(provider, max_input_tokens=5)
    big = [{"role": "user", "content": "x" * 400}]
    with pytest.raises(BudgetExceededError):
        await gw.generate(big, budget)
    assert provider.calls == []


def test_tool_call_budget():
    budget = ExecutionBudget(BudgetLimits.from_settings(make_settings(max_tool_calls_per_request=1)))
    budget.ensure_tool_call()
    budget.record_tool_call()
    with pytest.raises(BudgetExceededError):
        budget.ensure_tool_call()


def test_request_deadline_returns_504(harness_factory):
    async def slow(*_):
        await asyncio.sleep(1)

    h = harness_factory(make_settings(request_deadline_ms=50, llm_timeout_ms=5000),
                        llm_provider=ScriptedLLM([slow]))
    assert h.query().status_code == 504


# --- MCP resilience -----------------------------------------------------------------------
def resilient(inner, **kw):
    params = dict(timeout_s=0.05, max_retries=2, base_delay_s=0, max_delay_s=0)
    params.update(kw)
    metrics = MetricsRegistry()
    breaker = CircuitBreaker("mcp", params.pop("threshold", 100), 30)
    return ResilientMcpClient(inner, Telemetry(metrics, enabled=False), breaker, **params), metrics


async def test_mcp_timeout_is_retried_then_raised():
    class Slow:
        calls = 0

        async def call_tool(self, name, arguments):
            Slow.calls += 1
            await asyncio.sleep(1)

    client, metrics = resilient(Slow())
    with pytest.raises(DependencyTimeoutError):
        await client.call_tool("mcp_search_documents", {})
    assert Slow.calls == 3
    assert metrics.total("mcp_retries_total") == 2


async def test_mcp_validation_error_is_not_retried():
    inner = SpyMcp(errors=[InvalidDependencyResponseError("400", status_code=400)])
    client, _ = resilient(inner)
    with pytest.raises(InvalidDependencyResponseError):
        await client.call_tool("mcp_search_documents", {})
    assert len(inner.calls) == 1


async def test_circuit_breaker_opens_and_fails_fast():
    inner = SpyMcp(errors=[DependencyUnavailableError("down")] * 10)
    client, _ = resilient(inner, max_retries=0, threshold=2)
    for _ in range(2):
        with pytest.raises(DependencyUnavailableError):
            await client.call_tool("mcp_search_documents", {})
    with pytest.raises(DependencyUnavailableError) as exc:
        await client.call_tool("mcp_search_documents", {})
    assert exc.value.reason == "circuit_open:mcp"
    assert len(inner.calls) == 2  # third call never reached the dependency
