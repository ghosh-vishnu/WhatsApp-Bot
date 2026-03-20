"""
Redis connection pool for caching, deduplication, and rate limiting.
Falls back to a no-op stub when Redis is not available (dev mode).
"""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

_settings = get_settings()
_pool: Any = None
_redis_available: bool | None = None


class _FakeRedis:
    """In-memory stub used when Redis is not running (local dev without Redis)."""

    def __init__(self):
        self._store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None, **kw) -> None:
        self._store[key] = value

    async def delete(self, *keys: str) -> None:
        for k in keys:
            self._store.pop(k, None)

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        self._store.clear()

    def pipeline(self):
        return _FakePipeline(self)


class _FakePipeline:
    """Stub pipeline that mimics Redis pipeline for the rate limiter."""

    def __init__(self, fake: _FakeRedis):
        self._fake = fake
        self._results: list[Any] = []

    def zremrangebyscore(self, key, min_score, max_score):
        self._results.append(0)
        return self

    def zcard(self, key):
        self._results.append(0)
        return self

    def zadd(self, key, mapping):
        self._results.append(1)
        return self

    def expire(self, key, seconds):
        self._results.append(True)
        return self

    async def execute(self) -> list:
        return self._results


def _check_redis() -> bool:
    """Synchronously check if Redis is reachable."""
    try:
        import redis as sync_redis

        url = _settings.REDIS_URL
        r = sync_redis.from_url(url, socket_connect_timeout=2)
        r.ping()
        r.close()
        return True
    except Exception:
        return False


def get_redis_pool() -> Any:
    global _pool, _redis_available

    if _pool is not None:
        return _pool

    if _redis_available is None:
        _redis_available = _check_redis()

    if _redis_available:
        import redis.asyncio as aioredis

        _pool = aioredis.from_url(
            _settings.REDIS_URL,
            max_connections=_settings.REDIS_MAX_CONNECTIONS,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
        )
        # Log host only (never credentials)
        _safe_url = _settings.REDIS_URL.split("@")[-1].split("?")[0] if "@" in _settings.REDIS_URL else "redis"
        logger.info("redis_connected", host=_safe_url[:50])
    else:
        _pool = _FakeRedis()
        logger.warning("redis_not_available", detail="Using in-memory stub. Install and start Redis for full functionality.")

    return _pool


async def close_redis() -> None:
    global _pool, _redis_available
    if _pool is not None:
        await _pool.aclose()
        _pool = None
        _redis_available = None


async def redis_health_check() -> bool:
    try:
        pool = get_redis_pool()
        return await pool.ping()
    except Exception:
        return False
