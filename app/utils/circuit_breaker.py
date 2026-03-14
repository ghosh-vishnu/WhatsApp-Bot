"""
Circuit breaker pattern implementation for external API calls.
Prevents cascading failures when NSE/BSE APIs are down.

States:
  CLOSED   -> normal operation, failures increment counter
  OPEN     -> all calls short-circuited, wait for recovery timeout
  HALF_OPEN -> allow limited probe calls to test recovery
"""

from __future__ import annotations

import asyncio
import enum
import time
from typing import Any, Callable, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)


class CircuitState(str, enum.Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreakerError(Exception):
    """Raised when the circuit breaker is open and blocking calls."""

    def __init__(self, name: str, state: CircuitState, retry_after: float) -> None:
        self.name = name
        self.state = state
        self.retry_after = retry_after
        super().__init__(
            f"Circuit breaker '{name}' is {state.value}. Retry after {retry_after:.1f}s"
        )


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        half_open_max_calls: int = 3,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._half_open_calls = 0
        self._last_failure_time: Optional[float] = None
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN and self._last_failure_time:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
                logger.info("circuit_half_open", breaker=self.name)
        return self._state

    async def call(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        async with self._lock:
            current_state = self.state

            if current_state == CircuitState.OPEN:
                retry_after = self.recovery_timeout - (
                    time.monotonic() - (self._last_failure_time or 0)
                )
                raise CircuitBreakerError(self.name, current_state, max(0, retry_after))

            if current_state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self.half_open_max_calls:
                    raise CircuitBreakerError(self.name, current_state, 5.0)
                self._half_open_calls += 1

        try:
            result = await func(*args, **kwargs)
            await self._on_success()
            return result
        except Exception as exc:
            await self._on_failure()
            raise exc

    async def _on_success(self) -> None:
        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.half_open_max_calls:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._success_count = 0
                    logger.info("circuit_closed", breaker=self.name)
            else:
                self._failure_count = max(0, self._failure_count - 1)

    async def _on_failure(self) -> None:
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()
            logger.warning(
                "circuit_failure_recorded",
                breaker=self.name,
                failure_count=self._failure_count,
                threshold=self.failure_threshold,
            )
            if self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                self._success_count = 0
                logger.error("circuit_opened", breaker=self.name)

    async def reset(self) -> None:
        async with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._half_open_calls = 0
            self._last_failure_time = None
            logger.info("circuit_reset", breaker=self.name)

    def get_status(self) -> dict:
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
        }
