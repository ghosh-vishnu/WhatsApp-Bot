"""
PostgreSQL engine and session management via SQLAlchemy 2.0.

Provides both async sessions (for FastAPI) and sync sessions
(for background scheduler threads that have their own event loops).
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

_settings = get_settings()

_DATABASE_URL = _settings.DATABASE_URL
_ASYNC_URL = _DATABASE_URL
if _ASYNC_URL.startswith("postgresql://"):
    _ASYNC_URL = _ASYNC_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

# Async engine for FastAPI request handlers
engine = create_async_engine(
    _ASYNC_URL,
    pool_size=_settings.DB_POOL_SIZE,
    max_overflow=_settings.DB_MAX_OVERFLOW,
    pool_timeout=_settings.DB_POOL_TIMEOUT,
    pool_recycle=_settings.DB_POOL_RECYCLE,
    echo=_settings.DEBUG,
)

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Sync engine for background threads (scheduler direct mode)
_SYNC_URL = _DATABASE_URL
if _SYNC_URL.startswith("postgresql+asyncpg://"):
    _SYNC_URL = _SYNC_URL.replace("postgresql+asyncpg://", "postgresql://", 1)

sync_engine = create_engine(
    _SYNC_URL,
    pool_size=5,
    max_overflow=2,
    echo=_settings.DEBUG,
)

sync_session_factory = sessionmaker(
    bind=sync_engine,
    class_=Session,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    await engine.dispose()
    sync_engine.dispose()
