"""
General helper utilities: date parsing, text truncation, retry decorator.
"""

from __future__ import annotations

import asyncio
import functools
from datetime import datetime, timezone
from typing import Any, Callable, Optional, TypeVar

from app.utils.logger import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


def parse_datetime(date_str: Optional[str], fmt: str = "%d-%b-%Y %H:%M:%S") -> Optional[datetime]:
    """Safely parse a date string; returns None on failure."""
    if not date_str:
        return None
    for f in (fmt, "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y %H:%M:%S", "%d-%m-%Y %H:%M:%S"):
        try:
            dt = datetime.strptime(date_str.strip(), f)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    logger.warning("date_parse_failed", raw=date_str)
    return None


def truncate(text: str, max_length: int = 1000) -> str:
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def async_retry(
    max_attempts: int = 3,
    backoff_factor: float = 1.5,
    exceptions: tuple = (Exception,),
) -> Callable:
    """Decorator for async functions that retries on specified exceptions."""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: Optional[Exception] = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt < max_attempts:
                        wait = backoff_factor ** attempt
                        logger.warning(
                            "retry_attempt",
                            function=func.__name__,
                            attempt=attempt,
                            max_attempts=max_attempts,
                            wait_seconds=wait,
                            error=str(exc),
                        )
                        await asyncio.sleep(wait)
            raise last_exc  # type: ignore[misc]

        return wrapper

    return decorator


def chunk_list(lst: list, size: int) -> list[list]:
    """Split a list into chunks of the given size."""
    return [lst[i : i + size] for i in range(0, len(lst), size)]
