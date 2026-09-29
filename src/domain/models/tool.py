from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from domain.models.document import Document


class ToolDefinition(BaseModel):
    """Explicit declaration of a tool.

    ``model_arguments`` are the only arguments described to the LLM. Any
    security-relevant argument is produced by the server and always overrides
    whatever the model sent.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    description: str = ""
    read_only: bool = True
    system_only: bool = False
    model_arguments: tuple[str, ...] = ()

    def llm_schema(self) -> dict[str, Any]:
        """Tool description in the (widely used) JSON-schema function format."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {arg: {"type": "string"} for arg in self.model_arguments},
                "required": list(self.model_arguments),
            },
        }


class ToolCall(BaseModel):
    """A tool call *proposed* by the LLM. Untrusted: name and arguments included."""

    model_config = ConfigDict(frozen=True)

    id: str = ""
    name: str
    arguments: Any = Field(default_factory=dict)


class ToolExecutionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool_name: str
    documents: tuple[Document, ...] = ()
