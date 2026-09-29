"""Explicit tool registry.

Adding a tool = ToolDefinition + handler + server-argument builder + RBAC config.
The orchestrator does not change.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from domain.models.permissions import AccessScope
from domain.models.tool import ToolDefinition, ToolExecutionResult
from ports.mcp import McpClientPort

ToolHandler = Callable[[dict[str, Any]], Awaitable[ToolExecutionResult]]
# Produces the security-relevant arguments from server state only.
ServerArgumentBuilder = Callable[[AccessScope, str], dict[str, Any]]


@dataclass(frozen=True)
class RegisteredTool:
    definition: ToolDefinition
    handler: ToolHandler | None
    server_arguments: ServerArgumentBuilder


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(
        self,
        definition: ToolDefinition,
        handler: ToolHandler | None = None,
        server_arguments: ServerArgumentBuilder = lambda scope, query: {},
    ) -> None:
        if definition.name in self._tools:
            raise ValueError(f"tool already registered: {definition.name}")
        if handler is None and not definition.system_only:
            raise ValueError("non-system tools need a handler")
        self._tools[definition.name] = RegisteredTool(definition, handler, server_arguments)

    def get(self, name: str) -> RegisteredTool | None:
        return self._tools.get(name)

    def definitions_for(self, scope: AccessScope) -> list[ToolDefinition]:
        """Tools the model may *see*: registered, not system-only, allowed for the employee."""
        return [
            t.definition for t in self._tools.values()
            if not t.definition.system_only and t.definition.name in scope.allowed_tools
        ]


SEARCH_DOCUMENTS = ToolDefinition(
    name="mcp_search_documents",
    description="Search internal documents relevant to the user question.",
    read_only=True,
    system_only=False,
    model_arguments=("query",),
)

GET_EMPLOYEE_PERMISSIONS = ToolDefinition(
    name="get_employee_permissions",
    description="Resolve employee permissions. Executed by the application only.",
    read_only=True,
    system_only=True,
)


def build_tool_registry(mcp: McpClientPort) -> ToolRegistry:
    registry = ToolRegistry()

    async def search_documents(arguments: dict[str, Any]) -> ToolExecutionResult:
        return await mcp.call_tool(SEARCH_DOCUMENTS.name, arguments)

    registry.register(
        SEARCH_DOCUMENTS,
        search_documents,
        server_arguments=lambda scope, query: {
            "query": query,
            "area_filter": scope.area,
            "classification_filter": list(scope.allowed_classifications),
        },
    )
    # Registered so the policy recognizes it and denies it explicitly; the
    # application calls it through PermissionsPort, never the LLM.
    registry.register(GET_EMPLOYEE_PERMISSIONS)
    return registry
