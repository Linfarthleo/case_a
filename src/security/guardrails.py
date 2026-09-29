"""Guardrail implementations of ``GuardrailPort`` and the input guardrail."""

import logging

from domain.exceptions import DependencyUnavailableError, InvalidRequestError
from ports.guardrail import GuardrailPort, GuardrailResult
from security.document_sanitizer import DocumentSanitizer
from security.injection_detector import InjectionDetector, normalize

logger = logging.getLogger(__name__)


class RuleBasedGuardrail:
    """Deterministic guardrail: detector + span sanitizer. No extra LLM cost."""

    name = "rule_based"

    def __init__(self, detector: InjectionDetector, sanitizer: DocumentSanitizer) -> None:
        self._detector = detector
        self._sanitizer = sanitizer

    def inspect(self, text: str) -> GuardrailResult:
        normalized = normalize(text)
        segments = self._detector.scan_segments(normalized)
        return GuardrailResult(
            finding=self._detector.summarize(segments),
            safe_text=self._sanitizer.sanitize(normalized, segments),
            guardrail=self.name,
        )


class FallbackGuardrail:
    """Primary guardrail (e.g. a future model-based classifier) with deterministic fallback.

    If the primary fails, the rule-based one is used. If no layer works, fail closed.
    """

    def __init__(self, primary: GuardrailPort, fallback: GuardrailPort) -> None:
        self._primary = primary
        self._fallback = fallback
        self.name = f"{primary.name}+{fallback.name}"

    def inspect(self, text: str) -> GuardrailResult:
        try:
            return self._primary.inspect(text)
        except Exception:
            logger.warning("guardrail_primary_failed", extra={"guardrail": self._primary.name})
        try:
            return self._fallback.inspect(text)
        except Exception as exc:
            raise DependencyUnavailableError("no_guardrail_available", retryable=False) from exc


class InputGuardrail:
    """Validates the (semi-trusted) user query before anything else runs."""

    def __init__(self, guardrail: GuardrailPort, max_chars: int) -> None:
        self._guardrail = guardrail
        self._max_chars = max_chars

    def validate(self, query: str) -> str:
        normalized = normalize(query).strip()
        if not normalized:
            raise InvalidRequestError("empty_query")
        if len(normalized) > self._max_chars:
            raise InvalidRequestError("query_too_long")
        if self._guardrail.inspect(normalized).finding.detected:
            # Direct injection attempt by the user: reject, fail secure.
            raise InvalidRequestError("query_injection_detected")
        return normalized
