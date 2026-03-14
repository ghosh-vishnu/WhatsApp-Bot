"""
FastAPI application entry point.

Boots up:
  - Structured logging
  - Database connection pool
  - Redis pool
  - Background scheduler
  - API routes
  - Error-handling middleware
"""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.health import router as health_router
from app.config import get_settings
from app.utils.logger import get_logger, setup_logging
from app.workers.scheduler import create_scheduler
from infra.database import close_db, init_db
from infra.redis import close_redis

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    setup_logging(
        log_level=settings.LOG_LEVEL,
        json_output=settings.APP_ENV != "development",
    )
    logger.info("app_starting", env=settings.APP_ENV)

    await init_db()
    logger.info("database_initialized")

    scheduler = create_scheduler()
    scheduler.start()
    logger.info("scheduler_started")

    yield

    scheduler.shutdown(wait=False)
    await close_db()
    await close_redis()
    logger.info("app_shutdown_complete")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="WhatsApp Stock Bot API",
        description="Automated stock market announcement service for WhatsApp Channels",
        version="1.0.0",
        docs_url="/docs" if settings.APP_ENV != "production" else None,
        redoc_url="/redoc" if settings.APP_ENV != "production" else None,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.APP_ENV == "development" else [],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_logging_middleware(request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        start = time.perf_counter()
        response: Response | None = None
        try:
            response = await call_next(request)
            return response
        finally:
            elapsed = round((time.perf_counter() - start) * 1000, 2)
            status = response.status_code if response else 500
            logger.info(
                "http_request",
                method=request.method,
                path=request.url.path,
                status=status,
                duration_ms=elapsed,
            )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "unhandled_exception",
            path=request.url.path,
            error_type=type(exc).__name__,
            error=str(exc)[:500],
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    app.include_router(health_router, prefix="/api/v1")

    return app


app = create_app()
