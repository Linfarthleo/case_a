"""Deterministic validation of the LLM answer before it leaves the system.

We do not ask the same LLM whether its answer is safe.
"""

import re

from domain.exceptions import SecurityViolationError
from domain.models.document import Citation, Document

_DOC_ID = re.compile(r"\bDOC-\d{1,6}\b")
_FORBIDDEN_MARKERS = (
    "security rules",
    "<untrusted_documents",
    "</document",
    "get_employee_permissions",
    "allowed_classifications",
    "allowed_tools",
    "classification_filter",
    "area_filter",
    "bearer ",
    "api_key",
)
_MIN_PROMPT_LINE_LEN = 25
_LIST_MARKER = re.compile(r"^\s*(\d+[.)]|[-*])\s*")


class OutputGuardrail:
    def __init__(
        self,
        system_prompt: str,
        max_chars: int,
        require_citations: bool,
        insufficient_info_answer: str,
    ) -> None:
        # Prompt sentences without list markers ("1. ", "- "), used to detect verbatim leaks.
        lines = (_LIST_MARKER.sub("", line).strip().casefold() for line in system_prompt.splitlines())
        self._prompt_lines = [line for line in lines if len(line) >= _MIN_PROMPT_LINE_LEN]
        self._max_chars = max_chars
        self._require_citations = require_citations
        self._insufficient = insufficient_info_answer.casefold()

    def validate(self, answer: str, documents: list[Document]) -> tuple[Citation, ...]:
        """Return the citations of the answer or raise ``SecurityViolationError``."""
        if not isinstance(answer, str) or not answer.strip():
            raise SecurityViolationError("empty_answer")
        if len(answer) > self._max_chars:
            raise SecurityViolationError("answer_too_long")

        lowered = answer.casefold()
        if any(marker in lowered for marker in _FORBIDDEN_MARKERS):
            raise SecurityViolationError("internal_marker_leak")
        if any(line in lowered for line in self._prompt_lines):
            raise SecurityViolationError("system_prompt_leak")

        by_id = {doc.id: doc for doc in documents}
        cited_ids = list(dict.fromkeys(_DOC_ID.findall(answer)))
        unknown = [doc_id for doc_id in cited_ids if doc_id not in by_id]
        if unknown:
            # References a document that was not retrieved/authorized for this request.
            raise SecurityViolationError("unauthorized_document_reference")

        if not cited_ids and self._require_citations and self._insufficient not in lowered:
            raise SecurityViolationError("missing_citations")

        return tuple(Citation(document_id=i, title=by_id[i].title) for i in cited_ids)
