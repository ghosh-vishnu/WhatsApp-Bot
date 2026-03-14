"""
Pydantic schemas for announcement data validation and serialization.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class SourceEnum(str, Enum):
    NSE = "NSE"
    BSE = "BSE"


class DeliveryStatusEnum(str, Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class AnnouncementCreate(BaseModel):
    """Inbound announcement from a fetcher service."""

    source: SourceEnum
    source_id: Optional[str] = None
    company_name: str = Field(..., min_length=1, max_length=512)
    symbol: Optional[str] = Field(default=None, max_length=64)
    title: str = Field(..., min_length=1)
    description: Optional[str] = None
    category: Optional[str] = Field(default=None, max_length=256)
    attachment_url: Optional[str] = None
    announcement_date: Optional[datetime] = None

    @field_validator("company_name", "title")
    @classmethod
    def _strip_whitespace(cls, v: str) -> str:
        return v.strip()


class AnnouncementResponse(BaseModel):
    id: int
    content_hash: str
    source: SourceEnum
    source_id: Optional[str]
    company_name: str
    symbol: Optional[str]
    title: str
    description: Optional[str]
    category: Optional[str]
    is_relevant: bool
    delivery_status: DeliveryStatusEnum
    delivery_attempts: int
    announcement_date: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AnnouncementListResponse(BaseModel):
    items: list[AnnouncementResponse]
    total: int
    page: int
    page_size: int


class HealthResponse(BaseModel):
    status: str
    database: str
    redis: str
    version: str
    uptime_seconds: float


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    result: Optional[str] = None
