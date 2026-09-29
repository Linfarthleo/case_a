from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AuditEventType(StrEnum):
    AUTH_SUCCESS = "AUTH_SUCCESS"
    AUTH_FAILED = "AUTH_FAILED"
    ACCESS_GRANTED = "ACCESS_GRANTED"
    ACCESS_DENIED = "ACCESS_DENIED"
    TOOL_ALLOWED = "TOOL_ALLOWED"
    TOOL_DENIED = "TOOL_DENIED"
    TOOL_ARGUMENTS_OVERRIDDEN = "TOOL_ARGUMENTS_OVERRIDDEN"
    DOCUMENT_RETRIEVED = "DOCUMENT_RETRIEVED"
    DOCUMENT_REJECTED = "DOCUMENT_REJECTED"
    PROMPT_INJECTION_DETECTED = "PROMPT_INJECTION_DETECTED"
    DOCUMENT_SANITIZED = "DOCUMENT_SANITIZED"
    INPUT_REJECTED = "INPUT_REJECTED"
    OUTPUT_REJECTED = "OUTPUT_REJECTED"
    QUERY_COMPLETED = "QUERY_COMPLETED"
    QUERY_FAILED = "QUERY_FAILED"


class AuditEvent(BaseModel):
    """Security event. Contains identifiers and decisions, never content or secrets."""

    model_config = ConfigDict(frozen=True)

    type: AuditEventType
    employee_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
