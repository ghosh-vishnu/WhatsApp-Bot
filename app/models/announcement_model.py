"""
SQLAlchemy ORM model for corporate announcements.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from infra.database import Base


class AnnouncementSource(str, enum.Enum):
    NSE = "NSE"
    BSE = "BSE"


class DeliveryStatus(str, enum.Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class Announcement(Base):
    __tablename__ = "announcements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    source: Mapped[AnnouncementSource] = mapped_column(Enum(AnnouncementSource), nullable=False)
    source_id: Mapped[str] = mapped_column(String(128), nullable=True)
    company_name: Mapped[str] = mapped_column(String(512), nullable=False)
    symbol: Mapped[str] = mapped_column(String(64), nullable=True, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(256), nullable=True, index=True)
    attachment_url: Mapped[str] = mapped_column(Text, nullable=True)
    announcement_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    is_relevant: Mapped[bool] = mapped_column(Boolean, default=False)
    delivery_status: Mapped[DeliveryStatus] = mapped_column(
        Enum(DeliveryStatus), default=DeliveryStatus.PENDING, nullable=False,
    )
    delivery_attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_delivery_error: Mapped[str] = mapped_column(Text, nullable=True)
    whatsapp_message_id: Mapped[str] = mapped_column(String(256), nullable=True)
    formatted_message: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )

    __table_args__ = (
        Index("ix_announcements_source_date", "source", "announcement_date"),
        Index("ix_announcements_status_created", "delivery_status", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Announcement id={self.id} source={self.source} company={self.company_name!r}>"
