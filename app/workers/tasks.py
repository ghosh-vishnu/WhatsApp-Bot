"""
Celery task definitions for the announcement pipeline.

Pipeline stages:
  1. fetch_and_process_announcements — scrape NSE/BSE, filter, deduplicate, store
  2. deliver_pending_messages        — send stored announcements via WhatsApp
  3. retry_failed_messages           — retry previously failed deliveries

Direct mode (no Redis/Celery): uses sync DB sessions to avoid async event-loop issues.
"""

from __future__ import annotations

import asyncio
from typing import Any

from celery import shared_task
from celery.utils.log import get_task_logger
from sqlalchemy import select, update, func

from app.config import get_settings
from app.models.announcement_model import Announcement, AnnouncementSource, DeliveryStatus
from app.repositories.announcement_repo import AnnouncementRepository
from app.schemas.announcement_schema import AnnouncementCreate
from app.services.alert_service import AlertService
from app.services.bse_service import BSEService
from app.services.filter_service import FilterService
from app.services.nse_service import NSEService
from app.services.summary_service import SummaryService
from app.services.whatsapp_service import WhatsAppService
from app.utils.circuit_breaker import CircuitBreaker, CircuitBreakerError
from app.utils.logger import get_logger, setup_logging
from app.utils.security import compute_content_hash
from infra.database import async_session_factory, sync_session_factory
from infra.redis import get_redis_pool

task_logger = get_task_logger(__name__)
logger = get_logger(__name__)

_nse_cb = CircuitBreaker(name="nse_api", failure_threshold=5, recovery_timeout=60)
_bse_cb = CircuitBreaker(name="bse_api", failure_threshold=5, recovery_timeout=60)


def _run_async(coro: Any) -> Any:
    """Run an async coroutine from a sync Celery task."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


# ── Celery tasks (used when Redis is available) ─────────────────────────

@shared_task(bind=True, name="app.workers.tasks.fetch_and_process_announcements", max_retries=2)
def fetch_and_process_announcements(self) -> dict:
    setup_logging()
    return _run_async(_async_fetch_and_process(self))


@shared_task(bind=True, name="app.workers.tasks.deliver_pending_messages", max_retries=1)
def deliver_pending_messages(self) -> dict:
    setup_logging()
    return _run_async(_async_deliver_pending())


@shared_task(bind=True, name="app.workers.tasks.retry_failed_messages", max_retries=0)
def retry_failed_messages(self) -> dict:
    setup_logging()
    return _run_async(_async_retry_failed())


# ── Async implementations (for Celery workers with their own event loop) ──

async def _async_fetch_and_process(task) -> dict:
    settings = get_settings()
    alert_svc = AlertService(settings)
    nse_svc = NSEService(settings, _nse_cb)
    bse_svc = BSEService(settings, _bse_cb)
    filter_svc = FilterService(settings)
    summary_svc = SummaryService()

    all_announcements: list[AnnouncementCreate] = []

    try:
        nse_data = await nse_svc.fetch_announcements(pages=2)
        all_announcements.extend(nse_data)
    except CircuitBreakerError:
        await alert_svc.alert_circuit_open("nse_api")
        logger.error("nse_circuit_open")
    except Exception as exc:
        await alert_svc.alert_fetch_failure("NSE", str(exc))
        logger.error("nse_fetch_failed", error=str(exc))
    finally:
        await nse_svc.close()

    try:
        bse_data = await bse_svc.fetch_announcements(pages=2)
        all_announcements.extend(bse_data)
    except CircuitBreakerError:
        await alert_svc.alert_circuit_open("bse_api")
        logger.error("bse_circuit_open")
    except Exception as exc:
        await alert_svc.alert_fetch_failure("BSE", str(exc))
        logger.error("bse_fetch_failed", error=str(exc))
    finally:
        await bse_svc.close()

    if not all_announcements:
        logger.info("no_announcements_fetched")
        return {"fetched": 0, "relevant": 0, "new": 0}

    relevant = filter_svc.filter_announcements(all_announcements)

    hashes = [
        compute_content_hash(a.source.value, a.company_name, a.title, a.description)
        for a in relevant
    ]

    redis = get_redis_pool()
    new_announcements: list[tuple[AnnouncementCreate, str]] = []
    for ann, h in zip(relevant, hashes):
        cache_key = f"dedup:{h}"
        if not await redis.get(cache_key):
            new_announcements.append((ann, h))
            await redis.set(cache_key, "1", ex=86400)

    stored = 0
    async with async_session_factory() as session:
        repo = AnnouncementRepository(session)
        existing_hashes = await repo.bulk_check_hashes([h for _, h in new_announcements])

        for ann, h in new_announcements:
            if h in existing_hashes:
                continue

            summary = summary_svc.generate_summary(ann)
            db_ann = Announcement(
                content_hash=h,
                source=AnnouncementSource(ann.source.value),
                source_id=ann.source_id,
                company_name=ann.company_name,
                symbol=ann.symbol,
                title=ann.title,
                description=ann.description,
                category=ann.category,
                attachment_url=ann.attachment_url,
                announcement_date=ann.announcement_date,
                is_relevant=True,
                delivery_status=DeliveryStatus.PENDING,
                formatted_message=summary,
            )
            await repo.upsert(db_ann)
            stored += 1

        await session.commit()

    result = {"fetched": len(all_announcements), "relevant": len(relevant), "new": stored}
    logger.info("pipeline_complete", **result)
    return result


async def _async_deliver_pending() -> dict:
    settings = get_settings()
    redis = get_redis_pool()
    wa_svc = WhatsAppService(settings, redis)
    alert_svc = AlertService(settings)
    sent = 0
    failed = 0

    try:
        async with async_session_factory() as session:
            repo = AnnouncementRepository(session)
            pending = await repo.get_pending(limit=50)

            for ann in pending:
                try:
                    if not ann.formatted_message:
                        await repo.mark_skipped(ann.id)
                        continue
                    result = await wa_svc.send_channel_message(ann.formatted_message)
                    await repo.mark_sent(ann.id, result.get("message_id", ""))
                    sent += 1
                except Exception as exc:
                    await repo.mark_failed(ann.id, str(exc))
                    failed += 1
                    logger.error("delivery_failed", announcement_id=ann.id, error=str(exc))

            await session.commit()

        if failed > 0 and (sent + failed) > 0:
            failure_rate = failed / (sent + failed) * 100
            if failure_rate > 30:
                await alert_svc.alert_high_failure_rate(failed, sent + failed, "batch")
    finally:
        await wa_svc.close()

    result = {"sent": sent, "failed": failed}
    logger.info("delivery_complete", **result)
    return result


async def _async_retry_failed() -> dict:
    settings = get_settings()
    redis = get_redis_pool()
    wa_svc = WhatsAppService(settings, redis)
    retried = 0
    still_failed = 0

    try:
        async with async_session_factory() as session:
            repo = AnnouncementRepository(session)
            failed_anns = await repo.get_failed_for_retry(max_attempts=3, limit=20)

            for ann in failed_anns:
                try:
                    if not ann.formatted_message:
                        await repo.mark_skipped(ann.id)
                        continue
                    result = await wa_svc.send_channel_message(ann.formatted_message)
                    await repo.mark_sent(ann.id, result.get("message_id", ""))
                    retried += 1
                except Exception as exc:
                    await repo.mark_failed(ann.id, str(exc))
                    still_failed += 1

            await session.commit()
    finally:
        await wa_svc.close()

    result = {"retried": retried, "still_failed": still_failed}
    logger.info("retry_complete", **result)
    return result


# ── Sync direct implementations (for scheduler without Redis) ────────────

def direct_fetch_and_process() -> dict:
    """Sync version: fetch announcements using httpx, store using sync DB."""
    settings = get_settings()
    filter_svc = FilterService(settings)
    summary_svc = SummaryService()
    nse_svc = NSEService(settings, _nse_cb)
    bse_svc = BSEService(settings, _bse_cb)

    all_announcements: list[AnnouncementCreate] = []

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        try:
            nse_data = loop.run_until_complete(nse_svc.fetch_announcements(pages=2))
            all_announcements.extend(nse_data)
        except Exception as exc:
            logger.error("nse_fetch_failed", error=str(exc)[:200])
        finally:
            loop.run_until_complete(nse_svc.close())

        try:
            bse_data = loop.run_until_complete(bse_svc.fetch_announcements(pages=2))
            all_announcements.extend(bse_data)
        except Exception as exc:
            logger.error("bse_fetch_failed", error=str(exc)[:200])
        finally:
            loop.run_until_complete(bse_svc.close())
    finally:
        loop.close()

    if not all_announcements:
        logger.info("no_announcements_fetched")
        return {"fetched": 0, "relevant": 0, "new": 0}

    relevant = filter_svc.filter_announcements(all_announcements)

    hashes = [
        compute_content_hash(a.source.value, a.company_name, a.title, a.description)
        for a in relevant
    ]

    stored = 0
    with sync_session_factory() as session:
        stmt = select(Announcement.content_hash).where(
            Announcement.content_hash.in_(hashes)
        )
        existing = {row[0] for row in session.execute(stmt).fetchall()}

        for ann, h in zip(relevant, hashes):
            if h in existing:
                continue

            summary = summary_svc.generate_summary(ann)
            db_ann = Announcement(
                content_hash=h,
                source=AnnouncementSource(ann.source.value),
                source_id=ann.source_id,
                company_name=ann.company_name,
                symbol=ann.symbol,
                title=ann.title,
                description=ann.description,
                category=ann.category,
                attachment_url=ann.attachment_url,
                announcement_date=ann.announcement_date,
                is_relevant=True,
                delivery_status=DeliveryStatus.PENDING,
                formatted_message=summary,
            )
            session.add(db_ann)
            stored += 1

        session.commit()

    result = {"fetched": len(all_announcements), "relevant": len(relevant), "new": stored}
    logger.info("pipeline_complete", **result)
    return result


def direct_deliver_pending() -> dict:
    """Sync version: query pending announcements and log them (WhatsApp needs async)."""
    sent = 0
    failed = 0

    with sync_session_factory() as session:
        stmt = (
            select(Announcement)
            .where(
                Announcement.delivery_status == DeliveryStatus.PENDING,
                Announcement.is_relevant.is_(True),
            )
            .order_by(Announcement.created_at.asc())
            .limit(50)
        )
        pending = session.execute(stmt).scalars().all()

        if not pending:
            return {"sent": 0, "failed": 0}

        settings = get_settings()
        redis = get_redis_pool()
        wa_svc = WhatsAppService(settings, redis)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            for ann in pending:
                if not ann.formatted_message:
                    ann.delivery_status = DeliveryStatus.SKIPPED
                    continue
                try:
                    result = loop.run_until_complete(
                        wa_svc.send_channel_message(ann.formatted_message)
                    )
                    ann.delivery_status = DeliveryStatus.SENT
                    ann.whatsapp_message_id = result.get("message_id", "")
                    ann.delivery_attempts += 1
                    sent += 1
                except Exception as exc:
                    ann.delivery_status = DeliveryStatus.FAILED
                    ann.delivery_attempts += 1
                    ann.last_delivery_error = str(exc)[:2000]
                    failed += 1
                    logger.error("delivery_failed", announcement_id=ann.id, error=str(exc)[:200])

            session.commit()
        finally:
            loop.run_until_complete(wa_svc.close())
            loop.close()

    result = {"sent": sent, "failed": failed}
    logger.info("delivery_complete", **result)
    return result


def direct_retry_failed() -> dict:
    """Sync version: retry failed deliveries."""
    retried = 0
    still_failed = 0

    with sync_session_factory() as session:
        stmt = (
            select(Announcement)
            .where(
                Announcement.delivery_status == DeliveryStatus.FAILED,
                Announcement.delivery_attempts < 3,
                Announcement.is_relevant.is_(True),
            )
            .order_by(Announcement.created_at.asc())
            .limit(20)
        )
        failed_anns = session.execute(stmt).scalars().all()

        if not failed_anns:
            return {"retried": 0, "still_failed": 0}

        settings = get_settings()
        redis = get_redis_pool()
        wa_svc = WhatsAppService(settings, redis)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            for ann in failed_anns:
                if not ann.formatted_message:
                    ann.delivery_status = DeliveryStatus.SKIPPED
                    continue
                try:
                    result = loop.run_until_complete(
                        wa_svc.send_channel_message(ann.formatted_message)
                    )
                    ann.delivery_status = DeliveryStatus.SENT
                    ann.whatsapp_message_id = result.get("message_id", "")
                    ann.delivery_attempts += 1
                    retried += 1
                except Exception as exc:
                    ann.delivery_attempts += 1
                    ann.last_delivery_error = str(exc)[:2000]
                    still_failed += 1

            session.commit()
        finally:
            loop.run_until_complete(wa_svc.close())
            loop.close()

    result = {"retried": retried, "still_failed": still_failed}
    logger.info("retry_complete", **result)
    return result
