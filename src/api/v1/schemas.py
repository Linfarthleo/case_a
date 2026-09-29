"""HTTP DTOs. Strict: unknown fields are rejected."""

from pydantic import BaseModel, ConfigDict, Field

_ID = r"^[A-Za-z0-9_-]{1,32}$"
_NAME = r"^[a-z0-9_-]{1,64}$"


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    # Part of the requested contract, but only COMPARED against server truth.
    employee_id: str = Field(pattern=_ID)
    role: str = Field(pattern=_NAME)
    area: str = Field(pattern=_NAME)
    query: str = Field(min_length=1, max_length=4000)


class CitationDTO(BaseModel):
    document_id: str
    title: str


class SecurityDTO(BaseModel):
    untrusted_content_detected: bool
    sanitized_documents: int


class QueryResponse(BaseModel):
    request_id: str
    answer: str
    citations: list[CitationDTO]
    security: SecurityDTO


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
