"""
Filtering engine for corporate announcements.
Applies keyword, category, and spam filters to determine relevance.
"""

from __future__ import annotations

from typing import Sequence

from app.config import Settings
from app.schemas.announcement_schema import AnnouncementCreate
from app.utils.logger import get_logger

logger = get_logger(__name__)


class FilterService:
    def __init__(self, settings: Settings) -> None:
        self._keywords = [kw.lower() for kw in settings.FILTER_KEYWORDS]
        self._categories = [cat.lower() for cat in settings.FILTER_CATEGORIES]
        self._spam = [sp.lower() for sp in settings.SPAM_KEYWORDS]

    def filter_announcements(
        self, announcements: Sequence[AnnouncementCreate],
    ) -> list[AnnouncementCreate]:
        """Return only relevant, non-spam announcements."""
        relevant: list[AnnouncementCreate] = []

        for ann in announcements:
            if self._is_spam(ann):
                logger.debug("announcement_filtered_spam", company=ann.company_name, title=ann.title[:80])
                continue
            if self._is_relevant(ann):
                relevant.append(ann)
            else:
                logger.debug("announcement_filtered_irrelevant", company=ann.company_name, title=ann.title[:80])

        logger.info(
            "filtering_complete",
            total_input=len(announcements),
            relevant=len(relevant),
            filtered_out=len(announcements) - len(relevant),
        )
        return relevant

    def _is_relevant(self, ann: AnnouncementCreate) -> bool:
        searchable = f"{ann.title} {ann.description or ''} {ann.category or ''}".lower()

        if any(kw in searchable for kw in self._keywords):
            return True

        if ann.category:
            cat_lower = ann.category.lower()
            if any(fc in cat_lower for fc in self._categories):
                return True

        return False

    def _is_spam(self, ann: AnnouncementCreate) -> bool:
        title_lower = ann.title.lower()
        return any(sp in title_lower for sp in self._spam)

    def is_announcement_relevant(self, ann: AnnouncementCreate) -> bool:
        """Check single announcement relevance (used by pipeline)."""
        return not self._is_spam(ann) and self._is_relevant(ann)
