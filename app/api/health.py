"""
Health check and monitoring endpoints.
"""

from __future__ import annotations

import time
import threading

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, get_redis, require_api_key
from app.repositories.announcement_repo import AnnouncementRepository
from app.schemas.announcement_schema import (
    AnnouncementListResponse,
    AnnouncementResponse,
    HealthResponse,
    TaskStatusResponse,
)
from app.utils.logger import get_logger
from infra.database import sync_session_factory

logger = get_logger(__name__)
router = APIRouter()

_start_time = time.time()


@router.get("/health", response_model=HealthResponse, tags=["monitoring"])
async def health_check() -> HealthResponse:
    """Comprehensive health check for all dependencies."""
    db_status = _check_db()
    redis_status = await _check_redis()

    overall = "healthy" if db_status == "healthy" and redis_status == "healthy" else "degraded"

    return HealthResponse(
        status=overall,
        database=db_status,
        redis=redis_status,
        version="1.0.0",
        uptime_seconds=round(time.time() - _start_time, 2),
    )


def _check_db() -> str:
    """Use sync connection for reliable DB health check."""
    try:
        with sync_session_factory() as session:
            session.execute(text("SELECT 1"))
        return "healthy"
    except Exception as exc:
        logger.error("health_db_failed", error=str(exc)[:200])
        return "unhealthy"


async def _check_redis() -> str:
    """Check Redis (returns healthy for FakeRedis stub too)."""
    try:
        from infra.redis import get_redis_pool
        pool = get_redis_pool()
        result = await pool.ping()
        return "healthy" if result else "unhealthy"
    except Exception as exc:
        logger.error("health_redis_failed", error=str(exc)[:200])
        return "unhealthy"


@router.get("/health/ready", tags=["monitoring"])
async def readiness_check() -> dict:
    """Kubernetes-style readiness probe."""
    db_ok = _check_db() == "healthy"
    return {"ready": db_ok}


@router.get("/health/live", tags=["monitoring"])
async def liveness_check() -> dict:
    """Kubernetes-style liveness probe."""
    return {"alive": True}


@router.get("/stats", tags=["monitoring"], dependencies=[Depends(require_api_key)])
async def get_stats(db: AsyncSession = Depends(get_db)) -> dict:
    """Return announcement processing statistics."""
    repo = AnnouncementRepository(db)
    return await repo.get_stats()


@router.get("/announcements", response_model=AnnouncementListResponse, tags=["announcements"])
async def list_announcements(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    source: str | None = Query(default=None),
    status: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> AnnouncementListResponse:
    """List announcements with pagination and optional filters."""
    repo = AnnouncementRepository(db)
    items, total = await repo.list_announcements(
        page=page, page_size=page_size, source=source, status=status,
    )
    return AnnouncementListResponse(
        items=[AnnouncementResponse.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/trigger/fetch", response_model=TaskStatusResponse, tags=["admin"], dependencies=[Depends(require_api_key)])
async def trigger_fetch() -> TaskStatusResponse:
    """Manually trigger announcement fetch pipeline."""
    from app.workers.scheduler import _should_use_celery

    if _should_use_celery():
        from app.workers.celery_app import celery_app
        result = celery_app.send_task(
            "app.workers.tasks.fetch_and_process_announcements", queue="fetch",
        )
        logger.info("manual_fetch_triggered", task_id=result.id)
        return TaskStatusResponse(task_id=result.id, status="queued")
    else:
        from app.workers.tasks import direct_fetch_and_process
        t = threading.Thread(target=direct_fetch_and_process, daemon=True)
        t.start()
        logger.info("manual_fetch_triggered", mode="direct")
        return TaskStatusResponse(task_id="direct", status="running")


@router.post("/trigger/deliver", response_model=TaskStatusResponse, tags=["admin"], dependencies=[Depends(require_api_key)])
async def trigger_deliver() -> TaskStatusResponse:
    """Manually trigger message delivery."""
    from app.workers.scheduler import _should_use_celery

    if _should_use_celery():
        from app.workers.celery_app import celery_app
        result = celery_app.send_task(
            "app.workers.tasks.deliver_pending_messages", queue="deliver",
        )
        logger.info("manual_deliver_triggered", task_id=result.id)
        return TaskStatusResponse(task_id=result.id, status="queued")
    else:
        from app.workers.tasks import direct_deliver_pending
        t = threading.Thread(target=direct_deliver_pending, daemon=True)
        t.start()
        logger.info("manual_deliver_triggered", mode="direct")
        return TaskStatusResponse(task_id="direct", status="running")
