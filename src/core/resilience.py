"""Small, explicit resilience primitives: bounded retries with jitter and a circuit breaker."""

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

from domain.exceptions import DependencyError, DependencyTimeoutError, DependencyUnavailableError

T = TypeVar("T")


def is_transient(exc: BaseException) -> bool:
    """Only dependency errors explicitly marked retryable (408/429/5xx/timeouts/resets)."""
    return isinstance(exc, DependencyError) and exc.retryable


def backoff_delay(attempt: int, base_s: float, max_s: float) -> float:
    """Exponential backoff with full jitter."""
    return random.uniform(0, min(max_s, base_s * (2 ** (attempt - 1))))


async def retry_async(
    operation: Callable[[], Awaitable[T]],
    *,
    max_retries: int,
    base_delay_s: float,
    max_delay_s: float,
    before_retry: Callable[[int, BaseException], None] | None = None,
) -> T:
    """Run ``operation`` with at most ``max_retries`` retries on transient errors.

    ``before_retry`` runs before every retry and may raise (e.g. BudgetExceededError)
    to stop retrying.
    """
    attempt = 0
    while True:
        try:
            return await operation()
        except Exception as exc:
            if attempt >= max_retries or not is_transient(exc):
                raise
            attempt += 1
            if before_retry:
                before_retry(attempt, exc)
            await asyncio.sleep(backoff_delay(attempt, base_delay_s, max_delay_s))


async def with_timeout(awaitable: Awaitable[T], timeout_s: float, reason: str) -> T:
    try:
        return await asyncio.wait_for(awaitable, timeout=timeout_s)
    except TimeoutError as exc:
        raise DependencyTimeoutError(reason) from exc


class CircuitBreaker:
    """Minimal closed/open/half-open breaker around an external dependency."""

    def __init__(self, name: str, failure_threshold: int, reset_timeout_s: float) -> None:
        self.name = name
        self._threshold = failure_threshold
        self._reset_timeout_s = reset_timeout_s
        self._failures = 0
        self._opened_at: float | None = None

    @property
    def state(self) -> str:
        if self._opened_at is None:
            return "closed"
        if time.monotonic() - self._opened_at >= self._reset_timeout_s:
            return "half_open"
        return "open"

    def before_call(self) -> None:
        if self.state == "open":
            raise DependencyUnavailableError(f"circuit_open:{self.name}", retryable=False)

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self, exc: BaseException) -> None:
        if not is_transient(exc):
            return  # client/validation errors say nothing about dependency health
        self._failures += 1
        if self._failures >= self._threshold or self.state == "half_open":
            self._opened_at = time.monotonic()

    async def call(self, operation: Callable[[], Awaitable[T]]) -> T:
        self.before_call()
        try:
            result = await operation()
        except Exception as exc:
            self.record_failure(exc)
            raise
        self.record_success()
        return result
