"""
Generates concise WhatsApp-friendly formatted messages from announcements.
"""

from __future__ import annotations

from app.schemas.announcement_schema import AnnouncementCreate
from app.utils.helpers import truncate
from app.utils.logger import get_logger

logger = get_logger(__name__)


class SummaryService:
    MAX_MESSAGE_LENGTH = 4096  # WhatsApp message limit

    def generate_summary(self, announcement: AnnouncementCreate) -> str:
        """Create a structured WhatsApp message from an announcement."""
        company = announcement.company_name.strip()
        title = announcement.title.strip()
        source = announcement.source.value
        symbol = announcement.symbol or ""
        category = announcement.category or ""
        description = announcement.description or ""

        symbol_line = f"Symbol: {symbol}\n" if symbol else ""
        category_line = f"Category: {category}\n" if category else ""
        desc_block = f"\nDetails:\n{truncate(description, 500)}\n" if description else ""

        message = (
            f"\U0001F4C8 *STOCK MARKET UPDATE*\n"
            f"\n"
            f"*Company:* {company}\n"
            f"{symbol_line}"
            f"{category_line}"
            f"\n"
            f"*Announcement:*\n"
            f"{truncate(title, 800)}\n"
            f"{desc_block}"
            f"\n"
            f"\U0001F4CD *Source:* {source}\n"
            f"\n"
            f"_Powered by StockBot_"
        )

        if len(message) > self.MAX_MESSAGE_LENGTH:
            message = message[: self.MAX_MESSAGE_LENGTH - 20] + "\n\n[Truncated]"

        return message

    def generate_batch_summary(self, announcements: list[AnnouncementCreate]) -> str:
        """Create a digest of multiple announcements (for batch mode)."""
        if not announcements:
            return ""

        header = (
            f"\U0001F4CA *MARKET UPDATES DIGEST*\n"
            f"_{len(announcements)} new announcement(s)_\n"
            f"{'=' * 30}\n\n"
        )

        items: list[str] = []
        for i, ann in enumerate(announcements[:10], 1):
            entry = (
                f"*{i}. {ann.company_name}*"
                f"{' (' + ann.symbol + ')' if ann.symbol else ''}\n"
                f"   {truncate(ann.title, 200)}\n"
                f"   _Source: {ann.source.value}_\n"
            )
            items.append(entry)

        footer = ""
        if len(announcements) > 10:
            footer = f"\n_...and {len(announcements) - 10} more_\n"

        message = header + "\n".join(items) + footer + "\n_Powered by StockBot_"

        if len(message) > self.MAX_MESSAGE_LENGTH:
            message = message[: self.MAX_MESSAGE_LENGTH - 20] + "\n\n[Truncated]"

        return message
