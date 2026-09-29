"""Audit sink writing JSON events to the dedicated ``audit`` logger.

In production this logger is routed to an access-controlled destination with
retention (e.g. Cloud Logging bucket with a locked retention policy / SIEM).
"""

import logging

from domain.models.audit import AuditEvent

_audit_logger = logging.getLogger("audit")


class LoggingAuditAdapter:
    def record(self, event: AuditEvent) -> None:
        try:
            _audit_logger.info(
                "audit_event",
                extra={
                    "audit_type": event.type.value,
                    "employee_id": event.employee_id,
                    "details": event.details,
                    "event_time": event.timestamp.isoformat(),
                },
            )
        except Exception:  # an audit sink failure is logged, never breaks the request path
            logging.getLogger(__name__).error("audit_write_failed")
