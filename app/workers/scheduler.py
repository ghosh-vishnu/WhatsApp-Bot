from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import get_settings
from app.utils.logger import get_logger, setup_logging

logger = get_logger(__name__)

_TASK_FETCH = "app.workers.tasks.fetch_and_process_announcements"
_TASK_DELIVER = "app.workers.tasks.deliver_pending_messages"
_TASK_RETRY = "app.workers.tasks.retry_failed_messages"


def _is_celery_available() -> bool:
    """Check if the Celery broker (Redis) is reachable."""
    settings = get_settings()
    broker_url = settings.CELERY_BROKER_URL
    if not broker_url or not broker_url.startswith("redis://"):
        return False
    try:
        import redis as sync_redis

        parts = broker_url.replace("redis://", "").split("/")
        host_port = parts[0].split(":")
        host = host_port[0] or "localhost"
        port = int(host_port[1]) if len(host_port) > 1 else 6379
        r = sync_redis.Redis(host=host, port=port, socket_connect_timeout=2)
        r.ping()
        r.close()
        return True
    except Exception:
        return False


_use_celery: bool | None = None


def _should_use_celery() -> bool:
    global _use_celery
    if _use_celery is None:
        _use_celery = _is_celery_available()
        if _use_celery:
            logger.info("scheduler_mode", mode="celery", detail="Redis broker available")
        else:
            logger.info("scheduler_mode", mode="direct", detail="Redis not available, running tasks in-process")
    return _use_celery


def _get_celery_app():
    from app.workers.celery_app import celery_app
    return celery_app


def _dispatch_fetch() -> None:
    if _should_use_celery():
        logger.info("scheduler_dispatching", task="fetch", mode="celery")
        _get_celery_app().send_task(_TASK_FETCH, queue="fetch")
    else:
        from app.workers.tasks import direct_fetch_and_process
        logger.info("scheduler_dispatching", task="fetch", mode="direct")
        try:
            result = direct_fetch_and_process()
            logger.info("task_completed", task="fetch", result=str(result))
        except Exception as exc:
            logger.error("task_failed", task="fetch", error=str(exc)[:300])


def _dispatch_deliver() -> None:
    if _should_use_celery():
        logger.info("scheduler_dispatching", task="deliver", mode="celery")
        _get_celery_app().send_task(_TASK_DELIVER, queue="deliver")
    else:
        from app.workers.tasks import direct_deliver_pending
        logger.info("scheduler_dispatching", task="deliver", mode="direct")
        try:
            result = direct_deliver_pending()
            logger.info("task_completed", task="deliver", result=str(result))
        except Exception as exc:
            logger.error("task_failed", task="deliver", error=str(exc)[:300])


def _dispatch_retry() -> None:
    if _should_use_celery():
        logger.info("scheduler_dispatching", task="retry", mode="celery")
        _get_celery_app().send_task(_TASK_RETRY, queue="deliver")
    else:
        from app.workers.tasks import direct_retry_failed
        logger.info("scheduler_dispatching", task="retry", mode="direct")
        try:
            result = direct_retry_failed()
            logger.info("task_completed", task="retry", result=str(result))
        except Exception as exc:
            logger.error("task_failed", task="retry", error=str(exc)[:300])


def create_scheduler() -> BackgroundScheduler:
    setup_logging()
    settings = get_settings()
    scheduler = BackgroundScheduler(timezone="Asia/Kolkata")

    scheduler.add_job(
        _dispatch_fetch,
        trigger=IntervalTrigger(seconds=settings.FETCH_INTERVAL_SECONDS),
        id="fetch_announcements",
        name="Fetch NSE/BSE announcements",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=60,
    )

    scheduler.add_job(
        _dispatch_deliver,
        trigger=IntervalTrigger(seconds=30),
        id="deliver_messages",
        name="Deliver pending WhatsApp messages",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=30,
    )

    scheduler.add_job(
        _dispatch_retry,
        trigger=IntervalTrigger(minutes=10),
        id="retry_failed",
        name="Retry failed deliveries",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=120,
    )

    logger.info(
        "scheduler_configured",
        fetch_interval=settings.FETCH_INTERVAL_SECONDS,
        deliver_interval=30,
        retry_interval=600,
    )
    return scheduler


if __name__ == "__main__":
    setup_logging()
    sched = create_scheduler()
    sched.start()
    logger.info("scheduler_started_standalone")

    try:
        import time
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        sched.shutdown()
        logger.info("scheduler_stopped")
