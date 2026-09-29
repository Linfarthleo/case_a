from contextlib import AbstractContextManager
from typing import Any, Protocol


class TelemetryPort(Protocol):
    """Traces + metrics. Implementations must never raise into business code."""

    def span(self, name: str, **attributes: Any) -> AbstractContextManager[Any]:
        ...

    def increment(self, metric: str, value: float = 1, **labels: str) -> None:
        ...

    def observe(self, metric: str, value: float, **labels: str) -> None:
        ...
