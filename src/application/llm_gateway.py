"""LLM gateway: timeout, cost-aware bounded retries, fallback model, breaker, metrics.

Before every provider invocation (first attempt or retry) it checks:
retry allowed AND tokens available AND cost available AND deadline not exceeded.
"""

import time
from typing import Any

from application.budget import ExecutionBudget, estimate_tokens
from core.config import Settings
from core.resilience import CircuitBreaker, retry_async, with_timeout
from domain.exceptions import DependencyError
from ports.llm import LLMConfig, LLMPort, LLMResponse, Message
from ports.telemetry import TelemetryPort


class LLMGateway:
    def __init__(
        self,
        provider: LLMPort,
        settings: Settings,
        telemetry: TelemetryPort,
        breaker: CircuitBreaker,
    ) -> None:
        self._provider = provider
        self._settings = settings
        self._telemetry = telemetry
        self._breaker = breaker

    async def generate(
        self,
        messages: list[Message],
        budget: ExecutionBudget,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        models = [self._settings.llm_model]
        if self._settings.llm_fallback_model:
            models.append(self._settings.llm_fallback_model)

        for index, model in enumerate(models):
            try:
                return await self._generate_with_retries(model, messages, tools, budget)
            except DependencyError as exc:
                is_last = index == len(models) - 1
                if is_last or not exc.retryable:
                    raise
                # Transient failure of the primary: fallback, still subject to the budget.
                self._telemetry.increment("llm_fallback_total", model=models[index + 1])

        raise AssertionError("unreachable")

    async def _generate_with_retries(
        self,
        model: str,
        messages: list[Message],
        tools: list[dict[str, Any]] | None,
        budget: ExecutionBudget,
    ) -> LLMResponse:
        estimated_input = estimate_tokens("".join(m["content"] for m in messages))

        def before_retry(_attempt: int, _exc: BaseException) -> None:
            budget.ensure_llm_retry()
            budget.record_llm_retry()
            self._telemetry.increment("llm_retries_total", model=model)

        return await retry_async(
            lambda: self._call_once(model, messages, tools, budget, estimated_input),
            max_retries=self._settings.llm_max_retries,
            base_delay_s=self._settings.retry_base_delay_ms / 1000,
            max_delay_s=self._settings.retry_max_delay_ms / 1000,
            before_retry=before_retry,
        )

    async def _call_once(
        self,
        model: str,
        messages: list[Message],
        tools: list[dict[str, Any]] | None,
        budget: ExecutionBudget,
        estimated_input: int,
    ) -> LLMResponse:
        max_output = min(self._settings.llm_max_output_tokens_per_call,
                         max(budget.remaining_output_tokens(), 0))
        # Raises BudgetExceededError BEFORE the provider is called.
        budget.ensure_llm_call(estimated_input, max_output)
        budget.record_llm_call()

        timeout_s = min(self._settings.llm_timeout_ms / 1000, budget.remaining_s())
        config = LLMConfig(model=model, max_output_tokens=max_output,
                           temperature=self._settings.llm_temperature, timeout_s=timeout_s)

        self._telemetry.increment("llm_calls_total", model=model)
        started = time.perf_counter()
        try:
            response = await self._breaker.call(
                lambda: with_timeout(self._provider.generate(messages, tools, config),
                                     timeout_s, "llm_timeout")
            )
        except DependencyError as exc:
            self._telemetry.increment("llm_errors_total", model=model, error=exc.code)
            raise
        finally:
            self._telemetry.observe("llm_duration_ms", (time.perf_counter() - started) * 1000,
                                    model=model)

        cost = budget.record_usage(response.usage)
        self._telemetry.increment("llm_input_tokens", response.usage.input_tokens, model=model)
        self._telemetry.increment("llm_output_tokens", response.usage.output_tokens, model=model)
        self._telemetry.increment("llm_estimated_cost", cost, model=model)
        return response
