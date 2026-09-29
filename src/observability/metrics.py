"""In-process metrics registry, mirrored to OpenTelemetry metrics when enabled.

The in-memory snapshot backs the ``/metrics`` endpoint and the tests; the OTel
mirror lets an exporter ship the same series to a real backend.
"""

import threading
from collections import defaultdict
from typing import Any

from opentelemetry import metrics as otel_metrics


def _key(metric: str, labels: dict[str, str]) -> str:
    if not labels:
        return metric
    return metric + "{" + ",".join(f"{k}={v}" for k, v in sorted(labels.items())) + "}"


class MetricsRegistry:
    def __init__(self, otel_enabled: bool = False) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, float] = defaultdict(float)
        self._histograms: dict[str, dict[str, float]] = {}
        self._meter = otel_metrics.get_meter("secure-rag-agent") if otel_enabled else None
        self._instruments: dict[str, Any] = {}

    def increment(self, metric: str, value: float = 1, **labels: str) -> None:
        with self._lock:
            self._counters[_key(metric, labels)] += value
        if self._meter:
            self._instrument(metric, "counter").add(value, labels)

    def observe(self, metric: str, value: float, **labels: str) -> None:
        with self._lock:
            h = self._histograms.setdefault(
                _key(metric, labels), {"count": 0, "sum": 0.0, "max": 0.0}
            )
            h["count"] += 1
            h["sum"] += value
            h["max"] = max(h["max"], value)
        if self._meter:
            self._instrument(metric, "histogram").record(value, labels)

    def counter(self, metric: str, **labels: str) -> float:
        with self._lock:
            return self._counters.get(_key(metric, labels), 0.0)

    def total(self, metric: str) -> float:
        """Sum of a counter across all label combinations."""
        with self._lock:
            return sum(v for k, v in self._counters.items() if k.split("{")[0] == metric)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {"counters": dict(self._counters), "histograms": dict(self._histograms)}

    def _instrument(self, metric: str, kind: str) -> Any:
        if metric not in self._instruments:
            assert self._meter is not None
            create = self._meter.create_counter if kind == "counter" else self._meter.create_histogram
            self._instruments[metric] = create(metric)
        return self._instruments[metric]
