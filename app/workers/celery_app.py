"""
Celery application factory.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from celery import Celery

from app.config import get_settings

_settings = get_settings()

celery_app = Celery(
    "whatsapp_stock_bot",
    broker=_settings.CELERY_BROKER_URL,
    backend=_settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Kolkata",
    enable_utc=True,
    task_soft_time_limit=_settings.CELERY_TASK_SOFT_TIME_LIMIT,
    task_time_limit=_settings.CELERY_TASK_TIME_LIMIT,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    task_track_started=True,
    worker_max_tasks_per_child=200,
    broker_connection_retry_on_startup=True,
    result_expires=3600,
    task_routes={
        "app.workers.tasks.fetch_and_process_announcements": {"queue": "fetch"},
        "app.workers.tasks.deliver_pending_messages": {"queue": "deliver"},
        "app.workers.tasks.retry_failed_messages": {"queue": "deliver"},
    },
)

celery_app.conf.beat_schedule = {
    "fetch-announcements": {
        "task": "app.workers.tasks.fetch_and_process_announcements",
        "schedule": _settings.FETCH_INTERVAL_SECONDS,
        "options": {"queue": "fetch"},
    },
    "deliver-pending": {
        "task": "app.workers.tasks.deliver_pending_messages",
        "schedule": 30.0,
        "options": {"queue": "deliver"},
    },
    "retry-failed": {
        "task": "app.workers.tasks.retry_failed_messages",
        "schedule": 600.0,
        "options": {"queue": "deliver"},
    },
}

celery_app.autodiscover_tasks(["app.workers"])
