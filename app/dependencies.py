"""
FastAPI dependency injection providers.
"""

from __future__ import annotations

from typing import AsyncGenerator

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
