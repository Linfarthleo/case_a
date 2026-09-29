from typing import Protocol

from pydantic import BaseModel, ConfigDict

from domain.models.document import InjectionFinding


class GuardrailResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    finding: InjectionFinding
    safe_text: str
    guardrail: str


class GuardrailPort(Protocol):
    """Detects and neutralizes instructions hidden in untrusted text.

    Implementations: RuleBasedGuardrail (MVP), ModelGuardrail / Hybrid (future).
    """

    name: str

    def inspect(self, text: str) -> GuardrailResult:
        ...
