"""Circuit breaker and retry logic for external API calls.

Protects against cascading failures when upstream services (arXiv, GitHub,
Semantic Scholar, etc.) are unhealthy.
"""
from __future__ import annotations

import time
import functools
import threading
from enum import Enum
from typing import Callable, TypeVar

from core.logging import get_logger

log = get_logger("resilience")

T = TypeVar("T")


class CircuitState(Enum):
    CLOSED = "closed"       # Normal operation
    OPEN = "open"           # Failing, reject calls
    HALF_OPEN = "half_open" # Testing if recovered


class CircuitBreaker:
    """Circuit breaker pattern for external API protection."""

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        expected_exceptions: tuple = (Exception,),
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exceptions = expected_exceptions

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._success_count = 0
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            if self._state == CircuitState.OPEN:
                if time.time() - self._last_failure_time >= self.recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    log.info("Circuit '%s' → HALF_OPEN (testing recovery)", self.name)
            return self._state

    def call(self, func: Callable[..., T], *args, **kwargs) -> T:
        state = self.state

        if state == CircuitState.OPEN:
            remaining = self.recovery_timeout - (time.time() - self._last_failure_time)
            raise CircuitOpenError(
                f"Circuit '{self.name}' is OPEN. "
                f"Recovery in {remaining:.0f}s"
            )

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except self.expected_exceptions as e:
            self._on_failure(e)
            raise

    def _on_success(self):
        with self._lock:
            self._failure_count = 0
            self._success_count += 1
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.CLOSED
                log.info("Circuit '%s' recovered → CLOSED", self.name)

    def _on_failure(self, error: Exception):
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            if self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                log.error(
                    "Circuit '%s' tripped → OPEN after %d failures: %s",
                    self.name, self._failure_count, error,
                )


class CircuitOpenError(Exception):
    """Raised when a circuit breaker is open and rejecting calls."""
    pass


# Global circuit breakers per external service
_breakers: dict[str, CircuitBreaker] = {}
_breaker_lock = threading.Lock()


def get_breaker(name: str) -> CircuitBreaker:
    """Get or create a named circuit breaker (thread-safe singleton)."""
    if name not in _breakers:
        with _breaker_lock:
            if name not in _breakers:
                _breakers[name] = CircuitBreaker(name=name)
    return _breakers[name]


def with_retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exponential_base: float = 2.0,
    retryable_exceptions: tuple = (Exception,),
):
    """Decorator: retry with exponential backoff + jitter."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            import random
            last_error = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_error = e
                    if attempt < max_retries:
                        delay = min(base_delay * (exponential_base ** attempt), max_delay)
                        # Add jitter (±25%)
                        delay *= 0.75 + random.random() * 0.5
                        log.warning(
                            "Retry %d/%d for %s (delay=%.1fs): %s",
                            attempt + 1, max_retries, func.__name__, delay, e,
                        )
                        time.sleep(delay)
            raise last_error
        return wrapper
    return decorator
