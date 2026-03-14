"""
Tests for the circuit breaker utility.
"""

from __future__ import annotations

import pytest

from app.utils.circuit_breaker import CircuitBreaker, CircuitBreakerError, CircuitState


class TestCircuitBreaker:
    @pytest.mark.asyncio
    async def test_starts_closed(self):
        cb = CircuitBreaker(name="test", failure_threshold=3)
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_opens_after_threshold(self):
        cb = CircuitBreaker(name="test", failure_threshold=3, recovery_timeout=300)

        async def failing():
            raise RuntimeError("fail")

        for _ in range(3):
            with pytest.raises(RuntimeError):
                await cb.call(failing)

        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_open_circuit_rejects_calls(self):
        cb = CircuitBreaker(name="test", failure_threshold=1, recovery_timeout=300)

        async def failing():
            raise RuntimeError("fail")

        with pytest.raises(RuntimeError):
            await cb.call(failing)

        with pytest.raises(CircuitBreakerError):
            await cb.call(failing)

    @pytest.mark.asyncio
    async def test_successful_call_in_closed_state(self):
        cb = CircuitBreaker(name="test", failure_threshold=3)

        async def success():
            return "ok"

        result = await cb.call(success)
        assert result == "ok"
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_reset(self):
        cb = CircuitBreaker(name="test", failure_threshold=1, recovery_timeout=300)

        async def failing():
            raise RuntimeError("fail")

        with pytest.raises(RuntimeError):
            await cb.call(failing)

        assert cb.state == CircuitState.OPEN
        await cb.reset()
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_get_status(self):
        cb = CircuitBreaker(name="test_api", failure_threshold=5, recovery_timeout=60)
        status = cb.get_status()
        assert status["name"] == "test_api"
        assert status["state"] == "CLOSED"
        assert status["failure_threshold"] == 5
