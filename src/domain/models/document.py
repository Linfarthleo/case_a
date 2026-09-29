from pydantic import BaseModel, ConfigDict, Field


class Document(BaseModel):
    """A document returned by retrieval. Its ``text`` is untrusted DATA."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=256)
    area: str
    classification: str
    text: str = Field(max_length=50_000)


class InjectionFinding(BaseModel):
    model_config = ConfigDict(frozen=True)

    detected: bool
    score: float
    matched_patterns: tuple[str, ...] = ()


class GuardedDocument(BaseModel):
    """Document after the guardrail: original metadata + neutralized text."""

    model_config = ConfigDict(frozen=True)

    document: Document
    safe_text: str
    finding: InjectionFinding

    @property
    def sanitized(self) -> bool:
        return self.finding.detected


class Citation(BaseModel):
    model_config = ConfigDict(frozen=True)

    document_id: str
    title: str


class AgentResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    answer: str
    citations: tuple[Citation, ...] = ()
    untrusted_content_detected: bool = False
    sanitized_documents: int = 0
