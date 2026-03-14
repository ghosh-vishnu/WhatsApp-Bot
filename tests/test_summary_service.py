"""
Tests for the summary / message generation service.
"""

from __future__ import annotations

import pytest

from app.schemas.announcement_schema import AnnouncementCreate, SourceEnum
from app.services.summary_service import SummaryService


class TestSummaryService:
    def setup_method(self):
        self.svc = SummaryService()

    def test_basic_summary_generation(self, sample_announcement):
        msg = self.svc.generate_summary(sample_announcement)
        assert "STOCK MARKET UPDATE" in msg
        assert "Reliance Industries Ltd" in msg
        assert "Board Meeting" in msg
        assert "NSE" in msg

    def test_summary_includes_symbol(self):
        ann = AnnouncementCreate(
            source=SourceEnum.BSE,
            company_name="HDFC Bank",
            symbol="HDFCBANK",
            title="Dividend Declared",
        )
        msg = self.svc.generate_summary(ann)
        assert "HDFCBANK" in msg
        assert "BSE" in msg

    def test_summary_without_symbol(self):
        ann = AnnouncementCreate(
            source=SourceEnum.NSE,
            company_name="Some Company",
            title="Some Announcement",
        )
        msg = self.svc.generate_summary(ann)
        assert "Symbol:" not in msg

    def test_summary_respects_max_length(self):
        long_desc = "A" * 5000
        ann = AnnouncementCreate(
            source=SourceEnum.NSE,
            company_name="Test Co",
            title="Test",
            description=long_desc,
        )
        msg = self.svc.generate_summary(ann)
        assert len(msg) <= SummaryService.MAX_MESSAGE_LENGTH

    def test_batch_summary(self, sample_announcements):
        msg = self.svc.generate_batch_summary(sample_announcements)
        assert "MARKET UPDATES DIGEST" in msg
        assert "5 new announcement" in msg

    def test_batch_summary_empty(self):
        assert self.svc.generate_batch_summary([]) == ""

    def test_summary_contains_powered_by(self, sample_announcement):
        msg = self.svc.generate_summary(sample_announcement)
        assert "Powered by StockBot" in msg

    def test_summary_with_category(self):
        ann = AnnouncementCreate(
            source=SourceEnum.NSE,
            company_name="ITC",
            title="AGM Notice",
            category="AGM/EGM",
        )
        msg = self.svc.generate_summary(ann)
        assert "Category: AGM/EGM" in msg
