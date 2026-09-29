"""Tool allowlist and server-authoritative argument policy."""

from typing import Any

from domain.exceptions import InvalidToolArgumentsError, ToolNotAllowedError
from domain.models.permissions import AccessScope
from domain.models.tool import ToolCall, ToolDefinition


class ToolPolicy:
    """Every tool call proposed by the LLM goes through here before execution.

    This check is repeated even though the model only *sees* allowed tools
    (defense in depth: the model may hallucinate or be manipulated).
    """

    def authorize(
        self, call: ToolCall, definition: ToolDefinition | None, scope: AccessScope
    ) -> ToolDefinition:
        if definition is None:
            raise ToolNotAllowedError("unknown_tool")
        if definition.system_only:
            raise ToolNotAllowedError("system_only_tool")
        if call.name not in scope.allowed_tools:
            raise ToolNotAllowedError("tool_not_in_allowlist")
        if not definition.read_only:
            raise ToolNotAllowedError("write_tools_not_supported")
        return definition


class ArgumentPolicy:
    """LLM arguments -> server-authoritative arguments.

    Only arguments declared in ``definition.model_arguments`` are taken from the
    model; ``server_arguments`` always win. Anything else the model sent (e.g.
    ``area_filter: "*"``) is dropped and reported as tampering.
    """

    def enforce(
        self,
        definition: ToolDefinition,
        llm_arguments: Any,
        server_arguments: dict[str, Any],
    ) -> tuple[dict[str, Any], list[str]]:
        if not isinstance(llm_arguments, dict):
            raise InvalidToolArgumentsError("arguments_not_an_object")

        overridden = sorted(
            key for key, value in llm_arguments.items()
            if key not in definition.model_arguments
            or (key in server_arguments and server_arguments[key] != value)
        )
        safe = {k: llm_arguments[k] for k in definition.model_arguments if k in llm_arguments}
        safe.update(server_arguments)
        return safe, overridden
