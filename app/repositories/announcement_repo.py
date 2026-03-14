"""
Data-access layer for announcements.
All database queries are isolated here for testability and separation of concerns.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.announcement_model import Announcement, DeliveryStatus


class AnnouncementRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def exists_by_hash(self, content_hash: str) -> bool:
        stmt = select(func.count()).where(Announcement.content_hash == content_hash)
        result = await self._session.execute(stmt)
        return (result.scalar() or 0) > 0

    async def bulk_check_hashes(self, hashes: list[str]) -> set[str]:
        """Return set of hashes that already exist in the database."""
        if not hashes:
            return set()
        stmt = select(Announcement.content_hash).where(
            Announcement.content_hash.in_(hashes)
        )
        result = await self._session.execute(stmt)
        return {row[0] for row in result.fetchall()}

    async def create(self, announcement: Announcement) -> Announcement:
        self._session.add(announcement)
        await self._session.flush()
        return announcement

    async def upsert(self, announcement: Announcement) -> Announcement:
        """Insert or skip on conflict (content_hash unique constraint)."""
        values = {
            "content_hash": announcement.content_hash,
            "source": announcement.source,
            "source_id": announcement.source_id,
            "company_name": announcement.company_name,
            "symbol": announcement.symbol,
            "title": announcement.title,
            "description": announcement.description,
            "category": announcement.category,
            "attachment_url": announcement.attachment_url,
            "announcement_date": announcement.announcement_date,
            "is_relevant": announcement.is_relevant,
            "delivery_status": announcement.delivery_status,
            "formatted_message": announcement.formatted_message,
        }
        stmt = (
            pg_insert(Announcement)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["content_hash"])
            .returning(Announcement.id)
        )
        result = await self._session.execute(stmt)
        row = result.fetchone()
        if row:
            announcement.id = row[0]
        await self._session.flush()
        return announcement

    async def get_pending(self, limit: int = 50) -> Sequence[Announcement]:
        stmt = (
            select(Announcement)
            .where(
                Announcement.delivery_status == DeliveryStatus.PENDING,
                Announcement.is_relevant.is_(True),
            )
            .order_by(Announcement.created_at.asc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def get_failed_for_retry(
        self, max_attempts: int = 3, limit: int = 20,
    ) -> Sequence[Announcement]:
        stmt = (
            select(Announcement)
            .where(
                Announcement.delivery_status == DeliveryStatus.FAILED,
                Announcement.delivery_attempts < max_attempts,
                Announcement.is_relevant.is_(True),
            )
            .order_by(Announcement.created_at.asc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def mark_sent(
        self, announcement_id: int, whatsapp_message_id: str,
    ) -> None:
        stmt = (
            update(Announcement)
            .where(Announcement.id == announcement_id)
            .values(
                delivery_status=DeliveryStatus.SENT,
                whatsapp_message_id=whatsapp_message_id,
                delivery_attempts=Announcement.delivery_attempts + 1,
                last_delivery_error=None,
            )
        )
        await self._session.execute(stmt)

    async def mark_failed(
        self, announcement_id: int, error: str,
    ) -> None:
        stmt = (
            update(Announcement)
            .where(Announcement.id == announcement_id)
            .values(
                delivery_status=DeliveryStatus.FAILED,
                delivery_attempts=Announcement.delivery_attempts + 1,
                last_delivery_error=error[:2000],
            )
        )
        await self._session.execute(stmt)

    async def mark_skipped(self, announcement_id: int) -> None:
        stmt = (
            update(Announcement)
            .where(Announcement.id == announcement_id)
            .values(delivery_status=DeliveryStatus.SKIPPED)
        )
        await self._session.execute(stmt)

    async def list_announcements(
        self,
        page: int = 1,
        page_size: int = 20,
        source: Optional[str] = None,
        status: Optional[str] = None,
    ) -> tuple[Sequence[Announcement], int]:
        base = select(Announcement)
        count_base = select(func.count()).select_from(Announcement)

        if source:
            base = base.where(Announcement.source == source)
            count_base = count_base.where(Announcement.source == source)
        if status:
            base = base.where(Announcement.delivery_status == status)
            count_base = count_base.where(Announcement.delivery_status == status)

        count_result = await self._session.execute(count_base)
        total = count_result.scalar() or 0

        stmt = (
            base.order_by(Announcement.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all(), total

    async def get_stats(self) -> dict:
        now = datetime.now(timezone.utc)
        day_ago = now - timedelta(days=1)

        total = await self._session.execute(
            select(func.count()).select_from(Announcement)
        )
        sent_24h = await self._session.execute(
            select(func.count())
            .select_from(Announcement)
            .where(
                Announcement.delivery_status == DeliveryStatus.SENT,
                Announcement.updated_at >= day_ago,
            )
        )
        failed_24h = await self._session.execute(
            select(func.count())
            .select_from(Announcement)
            .where(
                Announcement.delivery_status == DeliveryStatus.FAILED,
                Announcement.updated_at >= day_ago,
            )
        )
        pending = await self._session.execute(
            select(func.count())
            .select_from(Announcement)
            .where(Announcement.delivery_status == DeliveryStatus.PENDING)
        )

        return {
            "total_announcements": total.scalar() or 0,
            "sent_last_24h": sent_24h.scalar() or 0,
            "failed_last_24h": failed_24h.scalar() or 0,
            "pending": pending.scalar() or 0,
        }
