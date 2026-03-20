"""
FastAPI dependency injection providers.
"""

from __future__ import annotations

import hmac
from typing import AsyncGenerator

from fastapi import Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from infra.database import async_session_factory
from infra.redis import get_redis_pool


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_redis():
    return get_redis_pool()


def get_config():
    return get_settings()


async def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> str:
    """Protect admin endpoints with the app SECRET_KEY. Returns 401 for missing/invalid key."""
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header")
    settings = get_settings()
    if not hmac.compare_digest(x_api_key, settings.SECRET_KEY):
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key
