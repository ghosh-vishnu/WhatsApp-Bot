"""
Tests for the announcement filtering engine.
"""

from __future__ import annotations

import pytest

from app.schemas.announcement_schema import AnnouncementCreate, SourceEnum
from app.services.filter_service import FilterService


class TestFilterService:
    def _make_service(self, settings) -> FilterService:
        return FilterService(settings)

    def test_relevant_keyword_match(self, settings, sample_announcement):
        svc = self._make_service(settings)
        assert svc.is_announcement_relevant(sample_announcement) is True

    def test_irrelevant_announcement_filtered(self, settings):
        svc = self._make_service(settings)
        ann = AnnouncementCreate(
            source=SourceEnum.NSE,
            company_name="XYZ Corp",
            title="Change of registered office address",
            description="Address changed from A to B",
            category="General",
        )
        assert svc.is_announcement_relevant(ann) is False

    def test_spam_announcement_filtered(self, settings):
        svc = self._make_service(settings)
        ann = AnnouncementCreate(
            source=SourceEnum.BSE,
            company_name="ABC Ltd",
            title="Test Announcement - Please Ignore",
            description="This is a test filing",
            category="Corp. Action",
        )
        assert svc.is_announcement_relevant(ann) is False

    def test_batch_filtering(self, settings, sample_announcements):
        svc = self._make_service(settings)
        result = svc.filter_announcements(sample_announcements)
        assert len(result) >= 2
        company_names = [a.company_name for a in result]
        assert "TCS Ltd" in company_names
        assert "SBI" in company_names

    def test_category_match(self, settings):
        svc = self._make_service(settings)
        ann = AnnouncementCreate(
            source=SourceEnum.NSE,
            company_name="ITC Ltd",
            title="Notice of Meeting",
            description="Regular meeting notice",
            category="AGM/EGM",
        )
        assert svc.is_announcement_relevant(ann) is True

    def test_duplicate_keyword_in_spam_takes_priority(self, settings):
        svc = self._make_service(settings)
        ann = AnnouncementCreate(
            source=SourceEnum.NSE,
            company_name="Test Corp",
            title="Revised Dividend Declaration",
            description="Revised version of earlier announcement",
            category="Corp. Action",
        )
        assert svc.is_announcement_relevant(ann) is False

    def test_empty_list_returns_empty(self, settings):
        svc = self._make_service(settings)
        assert svc.filter_announcements([]) == []
