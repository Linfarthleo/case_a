"""Adapter for OpenAI-compatible Chat Completions APIs (OpenAI, Azure/vLLM gateways, ...).

Uses plain httpx to keep dependencies small. Maps provider failures to typed
errors with explicit retry semantics (retry: 408/429/5xx/timeouts/resets).
"""

import json
from typing import Any

import httpx
from pydantic import SecretStr

from domain.exceptions import (
    DependencyTimeoutError,
    DependencyUnavailableError,
    InvalidDependencyResponseError,
    dependency_error_from_status,
)
from domain.models.tool import ToolCall
from ports.llm import LLMConfig, LLMResponse, LLMUsage, Message


class OpenAICompatibleAdapter:
    def __init__(self, base_url: str, api_key: SecretStr, client: httpx.AsyncClient | None = None):
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._api_key = api_key
        self._client = client or httpx.AsyncClient()

    async def generate(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        config: LLMConfig | None = None,
    ) -> LLMResponse:
        if config is None:
            raise ValueError("config is required")
        payload: dict[str, Any] = {
            "model": config.model,
            "messages": messages,
            "max_tokens": config.max_output_tokens,
            "temperature": config.temperature,
        }
        if tools:
            payload["tools"] = [{"type": "function", "function": t} for t in tools]

        try:
            response = await self._client.post(
                self._url,
                json=payload,
                headers={"Authorization": f"Bearer {self._api_key.get_secret_value()}"},
                timeout=config.timeout_s,
            )
        except httpx.TimeoutException as exc:
            raise DependencyTimeoutError("llm_timeout") from exc
        except httpx.TransportError as exc:  # connection refused/reset
            raise DependencyUnavailableError("llm_connection_error") from exc

        if response.status_code >= 400:
            raise dependency_error_from_status(response.status_code, "llm_http_error")
        return self._parse(response, config.model)

    @staticmethod
    def _parse(response: httpx.Response, model: str) -> LLMResponse:
        try:
            body = response.json()
            message = body["choices"][0]["message"]
            usage = body.get("usage") or {}
            calls = []
            for raw in message.get("tool_calls") or []:
                arguments: Any = raw["function"].get("arguments") or "{}"
                try:
                    arguments = json.loads(arguments)
                except (TypeError, json.JSONDecodeError):
                    pass  # left as-is: ArgumentPolicy rejects non-object arguments (422)
                calls.append(ToolCall(id=raw.get("id", ""), name=raw["function"]["name"],
                                      arguments=arguments))
            return LLMResponse(
                content=message.get("content") or "",
                tool_calls=tuple(calls),
                model=body.get("model", model),
                usage=LLMUsage(
                    input_tokens=int(usage.get("prompt_tokens", 0)),
                    output_tokens=int(usage.get("completion_tokens", 0)),
                ),
            )
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise InvalidDependencyResponseError("llm_malformed_response") from exc
