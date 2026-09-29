"""Decorator adding timeout, bounded retries, circuit breaker and metrics to any MCP client."""

import time
from typing import Any

from core.resilience import CircuitBreaker, retry_async, with_timeout
from domain.exceptions import DependencyError
from domain.models.tool import ToolExecutionResult
from ports.mcp import McpClientPort
from ports.telemetry import TelemetryPort


class ResilientMcpClient:
    def __init__(
        self,
        inner: McpClientPort,
        telemetry: TelemetryPort,
        breaker: CircuitBreaker,
        timeout_s: float,
        max_retries: int,
        base_delay_s: float,
        max_delay_s: float,
    ) -> None:
        self._inner = inner
        self._telemetry = telemetry
        self._breaker = breaker
        self._timeout_s = timeout_s
        self._max_retries = max_retries
        self._base_delay_s = base_delay_s
        self._max_delay_s = max_delay_s

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolExecutionResult:
        async def attempt() -> ToolExecutionResult:
            self._telemetry.increment("mcp_calls_total", tool=name)
            started = time.perf_counter()
            try:
                return await self._breaker.call(
                    lambda: with_timeout(self._inner.call_tool(name, arguments),
                                         self._timeout_s, "mcp_timeout")
                )
            except DependencyError as exc:
                self._telemetry.increment("mcp_errors_total", tool=name, error=exc.code)
                raise
            finally:
                self._telemetry.observe(
                    "mcp_duration_ms", (time.perf_counter() - started) * 1000, tool=name
                )

        def on_retry(_attempt: int, _exc: BaseException) -> None:
            self._telemetry.increment("mcp_retries_total", tool=name)

        with self._telemetry.span("mcp." + name.removeprefix("mcp_")):
            return await retry_async(
                attempt,
                max_retries=self._max_retries,
                base_delay_s=self._base_delay_s,
                max_delay_s=self._max_delay_s,
                before_retry=on_retry,
            )
