"""Per-request execution budget. Prevents costly agentic loops.

Checked BEFORE every LLM call, retry and tool call. When exceeded the provider
is not invoked again.
"""

import time
from dataclasses import dataclass, field

from core.config import Settings
from domain.exceptions import BudgetExceededError
from ports.llm import LLMUsage


def estimate_tokens(text: str) -> int:
    """Cheap, provider-agnostic upper-bound-ish estimate (~4 chars per token)."""
    return max(1, len(text) // 4)


@dataclass
class BudgetLimits:
    max_llm_calls: int
    max_llm_retries: int
    max_tool_calls: int
    max_input_tokens: int
    max_output_tokens: int
    max_cost_usd: float
    deadline_s: float
    input_cost_per_1k: float
    output_cost_per_1k: float

    @classmethod
    def from_settings(cls, s: Settings) -> "BudgetLimits":
        return cls(
            max_llm_calls=s.max_llm_calls_per_request,
            max_llm_retries=s.max_llm_retries_per_request,
            max_tool_calls=s.max_tool_calls_per_request,
            max_input_tokens=s.max_input_tokens,
            max_output_tokens=s.max_output_tokens,
            max_cost_usd=s.max_estimated_cost_usd,
            deadline_s=s.request_deadline_ms / 1000,
            input_cost_per_1k=s.llm_input_cost_per_1k_tokens,
            output_cost_per_1k=s.llm_output_cost_per_1k_tokens,
        )


@dataclass
class ExecutionBudget:
    limits: BudgetLimits
    started_at: float = field(default_factory=time.monotonic)
    llm_calls: int = 0
    llm_retries: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    # --- queries -------------------------------------------------------------
    def remaining_s(self) -> float:
        return self.limits.deadline_s - (time.monotonic() - self.started_at)

    def remaining_output_tokens(self) -> int:
        return self.limits.max_output_tokens - self.output_tokens

    def _cost(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens * self.limits.input_cost_per_1k
                + output_tokens * self.limits.output_cost_per_1k) / 1000

    # --- guards (raise BudgetExceededError) ----------------------------------
    def ensure_llm_call(self, estimated_input_tokens: int, max_output_tokens: int) -> None:
        if self.llm_calls >= self.limits.max_llm_calls:
            raise BudgetExceededError("max_llm_calls")
        if self.input_tokens + estimated_input_tokens > self.limits.max_input_tokens:
            raise BudgetExceededError("max_input_tokens")
        if self.remaining_output_tokens() <= 0:
            raise BudgetExceededError("max_output_tokens")
        projected = self.cost_usd + self._cost(estimated_input_tokens, max_output_tokens)
        if projected > self.limits.max_cost_usd:
            raise BudgetExceededError("max_cost")
        if self.remaining_s() <= 0:
            raise BudgetExceededError("deadline")

    def ensure_llm_retry(self) -> None:
        if self.llm_retries >= self.limits.max_llm_retries:
            raise BudgetExceededError("max_llm_retries")

    def ensure_tool_call(self) -> None:
        if self.tool_calls >= self.limits.max_tool_calls:
            raise BudgetExceededError("max_tool_calls")
        if self.remaining_s() <= 0:
            raise BudgetExceededError("deadline")

    # --- recording -------------------------------------------------------------
    def record_llm_call(self) -> None:
        self.llm_calls += 1

    def record_llm_retry(self) -> None:
        self.llm_retries += 1

    def record_tool_call(self) -> None:
        self.tool_calls += 1

    def record_usage(self, usage: LLMUsage) -> float:
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        cost = self._cost(usage.input_tokens, usage.output_tokens)
        self.cost_usd += cost
        return cost
