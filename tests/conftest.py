"""
Shared test fixtures and configuration.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key-that-is-long-enough-32chars!")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test_db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/14")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://localhost:6379/13")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "test_phone_id")
os.environ.setdefault("WHATSAPP_ACCESS_TOKEN", "test_access_token")
os.environ.setdefault("APP_ENV", "development")


@pytest.fixture
def sample_announcement():
    from app.schemas.announcement_schema import AnnouncementCreate, SourceEnum

    return AnnouncementCreate(
        source=SourceEnum.NSE,
        source_id="12345",
        company_name="Reliance Industries Ltd",
        symbol="RELIANCE",
        title="Board Meeting - Quarterly Results",
        description="Board meeting to consider quarterly financial results for Q3 FY2026",
        category="Board Meeting",
        announcement_date=None,
    )


@pytest.fixture
def sample_announcements():
    from app.schemas.announcement_schema import AnnouncementCreate, SourceEnum

    return [
        AnnouncementCreate(
            source=SourceEnum.NSE,
            company_name="TCS Ltd",
            title="Dividend Declaration - Final Dividend",
            description="The board declared a final dividend of Rs 75 per share",
            category="Corp. Action",
        ),
        AnnouncementCreate(
            source=SourceEnum.BSE,
            company_name="HDFC Bank",
            symbol="HDFCBANK",
            title="Annual General Meeting Notice",
            description="Notice for AGM scheduled on September 15, 2026",
            category="AGM/EGM",
        ),
        AnnouncementCreate(
            source=SourceEnum.NSE,
            company_name="Infosys Ltd",
            symbol="INFY",
            title="General Company Update",
            description="Regular administrative update regarding office relocation",
            category="General",
        ),
        AnnouncementCreate(
            source=SourceEnum.BSE,
            company_name="Wipro Ltd",
            symbol="WIPRO",
            title="Test Announcement - Duplicate Correction",
            description="This is a test",
            category="General",
        ),
        AnnouncementCreate(
            source=SourceEnum.NSE,
            company_name="SBI",
            symbol="SBIN",
            title="Stock Split Announcement",
            description="Stock split in ratio 1:5",
            category="Corp. Action",
        ),
    ]


@pytest.fixture
def settings():
    from app.config import Settings

    return Settings(
        SECRET_KEY="test-secret-key-that-is-long-enough-32chars!",
        DATABASE_URL="postgresql://test:test@localhost:5432/test_db",
        WHATSAPP_PHONE_NUMBER_ID="test_id",
        WHATSAPP_ACCESS_TOKEN="test_token",
    )
