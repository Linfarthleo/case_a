"""Structured JSON logging with request/correlation/trace IDs on every line."""

import json
import logging
import sys
from datetime import UTC, datetime

from opentelemetry import trace

from core.context import correlation_id_var, request_id_var

_RESERVED = set(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


def current_trace_id() -> str | None:
    ctx = trace.get_current_span().get_span_context()
    return format(ctx.trace_id, "032x") if ctx.is_valid else None


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
            "request_id": request_id_var.get(),
            "correlation_id": correlation_id_var.get(),
            "trace_id": current_trace_id(),
        }
        payload.update({k: v for k, v in vars(record).items() if k not in _RESERVED})
        if record.exc_info:
            # Exception type only: stack traces can carry sensitive data.
            payload["exception_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # Audit events go to their own logger/stream so they can be routed separately.
    logging.getLogger("audit").propagate = True
