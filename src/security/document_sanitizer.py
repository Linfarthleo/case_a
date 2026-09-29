"""Neutralizes only the suspicious spans, keeping legitimate content."""

from security.injection_detector import SegmentFinding

REMOVED_MARKER = "[UNTRUSTED_INSTRUCTION_REMOVED]"


class DocumentSanitizer:
    def sanitize(self, normalized_text: str, findings: list[SegmentFinding]) -> str:
        result = normalized_text
        # Replace from the end so earlier offsets stay valid.
        for finding in sorted(findings, key=lambda f: f.start, reverse=True):
            result = result[: finding.start] + REMOVED_MARKER + result[finding.end:]
        return result
