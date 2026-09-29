"""Deterministic LLM used for local runs, tests and the evaluation demo.

- With tools available: proposes one call to the first tool with the user question.
- Without tools: writes an extractive answer from the documents in the prompt,
  citing their IDs, and skipping neutralized spans.
"""

import html
import re
from typing import Any

from domain.models.tool import ToolCall
from ports.llm import LLMConfig, LLMResponse, LLMUsage, Message
from security.document_sanitizer import REMOVED_MARKER
from security.injection_detector import SEGMENT_PATTERN

INSUFFICIENT_INFO_ANSWER = (
    "No encuentro información suficiente en los documentos autorizados para responder."
)

_DOC_BLOCK = re.compile(r'<document id="([^"]+)" title="([^"]*)">\n(.*?)\n</document>', re.S)


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class MockLLMAdapter:
    async def generate(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        config: LLMConfig | None = None,
    ) -> LLMResponse:
        prompt = "\n".join(m["content"] for m in messages)
        last_user = next(m["content"] for m in reversed(messages) if m["role"] == "user")
        model = config.model if config else "mock"

        if tools:
            call = ToolCall(id="call-1", name=tools[0]["name"], arguments={"query": last_user})
            return LLMResponse(
                tool_calls=(call,), model=model,
                usage=LLMUsage(input_tokens=_estimate_tokens(prompt), output_tokens=20),
            )

        answer = self._answer(last_user)
        return LLMResponse(
            content=answer, model=model,
            usage=LLMUsage(input_tokens=_estimate_tokens(prompt),
                           output_tokens=_estimate_tokens(answer)),
        )

    @staticmethod
    def _answer(user_message: str) -> str:
        lines = []
        for doc_id, _title, body in _DOC_BLOCK.findall(user_message):
            sentences = [
                s.strip() for s in SEGMENT_PATTERN.findall(html.unescape(body))
                if s.strip() and REMOVED_MARKER not in s
            ]
            if sentences:
                lines.append(f"- {sentences[0]} [{html.unescape(doc_id)}]")
        if not lines:
            return INSUFFICIENT_INFO_ANSWER
        return "Según los documentos autorizados:\n" + "\n".join(lines)
