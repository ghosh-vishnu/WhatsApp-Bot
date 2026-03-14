"""
Security utilities: hashing, rate limiting, header rotation, input sanitization.
"""

from __future__ import annotations

import hashlib
import html
import random
import re
import time
from typing import Optional

import redis.asyncio as aioredis

from app.utils.logger import get_logger

logger = get_logger(__name__)

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
]


def compute_content_hash(
    source: str,
    company: str,
    title: str,
    description: Optional[str] = None,
) -> str:
    """SHA-256 hash of normalized announcement content for deduplication."""
    normalised = f"{source.upper()}|{company.strip().lower()}|{title.strip().lower()}"
    if description:
        normalised += f"|{description.strip().lower()}"
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def get_rotating_headers() -> dict[str, str]:
    """Return browser-like headers with a random user-agent for anti-bot evasion."""
    return {
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Cache-Control": "no-cache",
    }


def sanitize_text(text: str) -> str:
    """Strip HTML tags and escape dangerous characters."""
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    return text.strip()


class RateLimiter:
    """Sliding-window rate limiter backed by Redis."""

    def __init__(
        self,
        redis: aioredis.Redis,
        key_prefix: str = "ratelimit",
        max_requests: int = 80,
        window_seconds: int = 60,
    ) -> None:
        self._redis = redis
        self._prefix = key_prefix
        self._max = max_requests
        self._window = window_seconds

    async def is_allowed(self, identifier: str) -> bool:
        key = f"{self._prefix}:{identifier}"
        now = time.time()
        pipe = self._redis.pipeline()
        pipe.zremrangebyscore(key, 0, now - self._window)
        pipe.zcard(key)
        pipe.zadd(key, {str(now): now})
        pipe.expire(key, self._window + 1)
        results = await pipe.execute()
        current_count = results[1]
        return current_count < self._max

    async def get_remaining(self, identifier: str) -> int:
        key = f"{self._prefix}:{identifier}"
        now = time.time()
        pipe = self._redis.pipeline()
        pipe.zremrangebyscore(key, 0, now - self._window)
        pipe.zcard(key)
        results = await pipe.execute()
        return max(0, self._max - results[1])
