from typing import Protocol

from domain.models.audit import AuditEvent


class AuditPort(Protocol):
    """Security/audit sink, separate from application logs."""

    def record(self, event: AuditEvent) -> None:
        ...
