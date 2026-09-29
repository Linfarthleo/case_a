from typing import Any, Protocol

from domain.models.tool import ToolExecutionResult


class McpClientPort(Protocol):
    """Client of an MCP server. Simulated today, real MCP client tomorrow."""

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolExecutionResult:
        ...
