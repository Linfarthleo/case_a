"""LLM port. Abstracts only what is used: chat, tool calling, usage and timeout."""

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from domain.models.tool import ToolCall


class LLMUsage(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_tokens: int = 0
    output_tokens: int = 0


class LLMConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    model: str
    max_output_tokens: int
    temperature: float = 0.0
    timeout_s: float = 10.0


class LLMResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    usage: LLMUsage = LLMUsage()
    model: str = ""


# Messages use the common {"role": ..., "content": ...} shape.
Message = dict[str, str]


class LLMPort(Protocol):
    async def generate(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        config: LLMConfig | None = None,
    ) -> LLMResponse:
        """Raise ``DependencyError`` subclasses with correct ``retryable`` semantics."""
        ...
