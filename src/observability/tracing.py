"""OpenTelemetry setup and a fail-safe telemetry facade (implements TelemetryPort)."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

from observability.metrics import MetricsRegistry

logger = logging.getLogger(__name__)
_provider_configured = False


def setup_tracing(service_name: str, exporter: str) -> None:
    """Install a TracerProvider once. Exporter failures never reach request handling."""
    global _provider_configured
    if _provider_configured:
        return
    try:
        from opentelemetry.sdk.resources import Resource

        provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
        if exporter == "console":
            # BatchSpanProcessor exports in a background thread and swallows exporter errors.
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        trace.set_tracer_provider(provider)
        _provider_configured = True
    except Exception:
        logger.warning("tracing_setup_failed")


class Telemetry:
    """Spans + metrics. Degrades safely: telemetry errors are logged, never raised."""

    def __init__(self, metrics: MetricsRegistry, enabled: bool = True) -> None:
        self.metrics = metrics
        self._tracer = trace.get_tracer("secure-rag-agent") if enabled else None

    @contextmanager
    def span(self, name: str, **attributes: Any) -> Iterator[Any]:
        if self._tracer is None:
            yield None
            return
        try:
            cm = self._tracer.start_as_current_span(name, attributes=attributes)
            span = cm.__enter__()
        except Exception:
            logger.warning("span_start_failed", extra={"span": name})
            yield None
            return
        error: BaseException | None = None
        try:
            yield span
        except BaseException as exc:
            error = exc
            raise
        finally:
            if error is not None:
                self._safe(lambda: span.set_attribute("error.type", type(error).__name__))
            self._safe(lambda: cm.__exit__(
                type(error) if error else None, error, error.__traceback__ if error else None))

    def increment(self, metric: str, value: float = 1, **labels: str) -> None:
        self._safe(lambda: self.metrics.increment(metric, value, **labels))

    def observe(self, metric: str, value: float, **labels: str) -> None:
        self._safe(lambda: self.metrics.observe(metric, value, **labels))

    @staticmethod
    def _safe(action: Any) -> None:
        try:
            action()
        except Exception:
            logger.warning("telemetry_failure")
