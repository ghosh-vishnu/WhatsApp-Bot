"""
Generates concise WhatsApp-friendly formatted messages from announcements.
ATLAS-style format with SUMMARY, IMPACT, STRENGTH, MARKET VIEW.
Uses LLM (OpenAI) when enabled, else rule-based fallback.
"""

from __future__ import annotations

import asyncio
from typing import Tuple

from app.schemas.announcement_schema import AnnouncementCreate
from app.utils.helpers import truncate
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Category → EVENT label mapping
_CATEGORY_TO_EVENT = {
    "agm/egm": "Shareholder Meeting",
    "board meeting": "Board Meeting",
    "corp. action": "Corporate Action",
    "result": "Financial Results",
    "insider trading": "Insider Trading",
    "company update": "Company Update",
    "shareholding": "Shareholding",
}

# Keywords that suggest bullish/bearish/neutral
_BULLISH_KEYWORDS = [
    "dividend", "bonus", "buyback", "merger", "acquisition", "deal", "contract",
    "profit", "growth", "allotment", "listing", "fund raising", "rights issue",
]
_BEARISH_KEYWORDS = [
    "delisting", "loss", "default", "resignation", "nclt", "insolvency",
    "fraud", "penalty", "cancellation",
]


class SummaryService:
    MAX_MESSAGE_LENGTH = 4096  # WhatsApp message limit

    def _infer_event(self, category: str, title: str) -> str:
        """Map category/title to EVENT label."""
        if category:
            cat_lower = category.lower().strip()
            for key, label in _CATEGORY_TO_EVENT.items():
                if key in cat_lower:
                    return label
        return category or truncate(title, 40).replace("\n", " ")

    def _infer_impact_and_strength(self, title: str, description: str, category: str) -> Tuple[str, int]:
        """Infer IMPACT and STRENGTH from content (rule-based fallback)."""
        text = f"{title} {description or ''} {category or ''}".lower()
        bullish_score = sum(1 for k in _BULLISH_KEYWORDS if k in text)
        bearish_score = sum(1 for k in _BEARISH_KEYWORDS if k in text)

        if bearish_score > bullish_score:
            impact = "Bearish"
            strength = min(7, 4 + bearish_score)
        elif bullish_score > bearish_score:
            impact = "Bullish"
            strength = min(8, 5 + bullish_score)
        else:
            impact = "Neutral"
            strength = 5

        if any(x in text for x in ["result", "board meeting", "dividend", "buyback"]):
            strength = min(9, strength + 1)
        return impact, strength

    def _build_summary(self, title: str, description: str, category: str) -> str:
        """Create a short SUMMARY from title + description."""
        if description and len(description) > 50:
            summary = truncate(description, 200).replace("\n", " ").strip()
        else:
            summary = truncate(title, 200).replace("\n", " ").strip()
        if not summary.endswith("."):
            summary += "."
        return summary

    def _infer_market_view(self, impact: str, strength: int) -> str:
        """Infer MARKET VIEW from impact and strength."""
        if impact == "Bullish" and strength >= 7:
            return "Positive for short to medium term"
        if impact == "Bearish" and strength >= 6:
            return "Cautious for short term"
        if impact == "Neutral":
            return "Monitor for further updates"
        return "Relevant for investors"

    def _format_message(
        self,
        company: str,
        symbol: str,
        source: str,
        event: str,
        summary: str,
        impact: str,
        strength: int,
        market_view: str,
    ) -> str:
        """Build ATLAS-style message from components."""
        symbol_line = f" | Symbol: {symbol}" if symbol else ""
        message = (
            f"\U0001F4E3 *ATLAS CORPORATE UPDATE*\n"
            f"{'─' * 28}\n"
            f"\U0001F3E2 *COMPANY:* {company}{symbol_line}\n"
            f"\U0001F4F0 *EVENT:* {event}\n"
            f"{'─' * 28}\n"
            f"\U0001F9E0 *SUMMARY:*\n"
            f"{summary}\n"
            f"{'─' * 28}\n"
            f"\U0001F4CA *IMPACT:* {impact}\n"
            f"\U0001F4A5 *STRENGTH:* {strength}/10\n"
            f"{'─' * 28}\n"
            f"\U0001F3AF *MARKET VIEW:*\n"
            f"{market_view}\n"
            f"{'─' * 28}\n"
            f"\U0001F4E9 *ATLAS Insight*\n"
            f"_Turning News into Decisions_\n"
            f"\n\U0001F4CD Source: {source}"
        )
        if len(message) > self.MAX_MESSAGE_LENGTH:
            message = message[: self.MAX_MESSAGE_LENGTH - 20] + "\n\n[Truncated]"
        return message

    async def generate_summary_async(self, announcement: AnnouncementCreate) -> str:
        """Create ATLAS-style message. Uses LLM when enabled, else rule-based."""
        from app.config import get_settings
        from app.services.llm_service import LLMAnalysis, LLMService

        company = announcement.company_name.strip()
        title = announcement.title.strip()
        source = announcement.source.value
        symbol = announcement.symbol or ""
        category = announcement.category or ""
        description = announcement.description or ""

        event = self._infer_event(category, title)
        settings = get_settings()

        analysis: LLMAnalysis | None = None
        if settings.LLM_ENABLED and settings.OPENAI_API_KEY:
            try:
                llm = LLMService()
                analysis = await llm.analyze_announcement(
                    company=company,
                    title=title,
                    description=description or "",
                    category=category,
                )
            except Exception as e:
                logger.warning("llm_fallback", error=str(e)[:100])

        if analysis:
            return self._format_message(
                company=company,
                symbol=symbol,
                source=source,
                event=event,
                summary=analysis.summary,
                impact=analysis.impact,
                strength=analysis.strength,
                market_view=analysis.market_view,
            )

        # Rule-based fallback
        summary = self._build_summary(title, description, category)
        impact, strength = self._infer_impact_and_strength(title, description, category)
        market_view = self._infer_market_view(impact, strength)
        return self._format_message(
            company=company,
            symbol=symbol,
            source=source,
            event=event,
            summary=summary,
            impact=impact,
            strength=strength,
            market_view=market_view,
        )

    def generate_summary(self, announcement: AnnouncementCreate) -> str:
        """Sync wrapper for generate_summary_async (used in direct_fetch mode)."""
        return asyncio.run(self.generate_summary_async(announcement))

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
