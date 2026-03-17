"""
NSE (National Stock Exchange) announcement fetcher.

Uses curl_cffi to impersonate real browser TLS fingerprints,
which is required to bypass NSE's aggressive bot detection
(Cloudflare + JA3/JA4 TLS fingerprinting).
"""

from __future__ import annotations

import asyncio
import random
from typing import Optional

from curl_cffi.requests import AsyncSession

from app.config import Settings
from app.schemas.announcement_schema import AnnouncementCreate, SourceEnum
from app.utils.circuit_breaker import CircuitBreaker
from app.utils.helpers import async_retry, parse_datetime
from app.utils.logger import get_logger
from app.utils.security import sanitize_text

logger = get_logger(__name__)

_BROWSERS = ["chrome120", "chrome119", "chrome116", "edge101", "safari15_5"]

HOMEPAGE = "https://www.nseindia.com"
API_BASE = "https://www.nseindia.com"
ANNOUNCEMENTS_URL = f"{API_BASE}/api/corporate-announcements"

_INDEX_SEGMENTS = ["equities", "sme", "debt", "mf"]


class NSEService:
    """Fetches corporate announcements from NSE India."""

    def __init__(self, settings: Settings, circuit_breaker: CircuitBreaker) -> None:
        self._settings = settings
        self._cb = circuit_breaker
        self._session: Optional[AsyncSession] = None
        self._warmed = False

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            self._session = AsyncSession(
                impersonate=random.choice(_BROWSERS),
                timeout=self._settings.REQUEST_TIMEOUT,
                allow_redirects=True,
            )
            await self._warm_session()
        return self._session

    async def _warm_session(self) -> None:
        """Hit NSE homepage to obtain session cookies before calling APIs."""
        try:
            resp = await self._session.get(  # type: ignore[union-attr]
                HOMEPAGE,
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept-Encoding": "gzip, deflate, br",
                },
            )
            if resp.status_code == 200:
                self._warmed = True
                logger.info("nse_session_warmed", status=resp.status_code)
            else:
                logger.warning("nse_session_warm_unexpected", status=resp.status_code)
        except Exception as exc:
            logger.warning("nse_session_warm_failed", error=str(exc))

    @async_retry(max_attempts=3, backoff_factor=2.0, exceptions=(Exception,))
    async def _fetch_segment(self, segment: str = "equities") -> list[dict]:
        """Fetch announcements for one NSE index segment (equities, sme, etc.)."""

        async def _do_fetch() -> list[dict]:
            session = await self._get_session()

            if not self._warmed:
                await self._warm_session()
                await asyncio.sleep(random.uniform(0.5, 1.5))

            headers = {
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Referer": f"{HOMEPAGE}/companies-listing/corporate-filings-announcements",
                "X-Requested-With": "XMLHttpRequest",
            }

            resp = await session.get(
                ANNOUNCEMENTS_URL,
                headers=headers,
                params={"index": segment},
            )
            resp.raise_for_status()
            data = resp.json()

            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                inner = data.get("data")
                return inner if isinstance(inner, list) else []
            return []

        return await self._cb.call(_do_fetch)

    async def fetch_announcements(self, pages: int = 2) -> list[AnnouncementCreate]:
        """Fetch latest announcements from NSE across index segments."""
        all_announcements: list[AnnouncementCreate] = []
        segments = _INDEX_SEGMENTS[:pages]

        for segment in segments:
            try:
                raw = await self._fetch_segment(segment=segment)
                parsed = [self._parse(item) for item in raw if item]
                all_announcements.extend([a for a in parsed if a is not None])
                logger.info(
                    "nse_segment_fetched",
                    segment=segment,
                    count=len(raw),
                    parsed=len(parsed),
                )
                await asyncio.sleep(random.uniform(1.0, 2.5))
            except Exception as exc:
                logger.error("nse_segment_fetch_error", segment=segment, error=str(exc))

        logger.info("nse_fetch_complete", total=len(all_announcements))
        return all_announcements

    def _parse(self, item: dict) -> Optional[AnnouncementCreate]:
        try:
            symbol = item.get("symbol", "") or ""
            subject = sanitize_text(item.get("desc", "") or "")
            company_name = sanitize_text(item.get("sm_name", "") or "")

            if not company_name or not subject:
                return None

            category = item.get("smIndustry", "") or item.get("attchmntText", "") or ""
            an_date = parse_datetime(item.get("an_dt"))
            sort_date = parse_datetime(item.get("sort_date"))
            attachment = item.get("attchmntFile", "")

            attachment_url = None
            if attachment:
                if attachment.startswith("http"):
                    attachment_url = attachment
                else:
                    attachment_url = f"{API_BASE}/corporate/content/{attachment}"

            return AnnouncementCreate(
                source=SourceEnum.NSE,
                source_id=item.get("seq_id", "") or None,
                company_name=company_name,
                symbol=symbol.strip() or None,
                title=subject,
                description=item.get("attchmntText"),
                category=category.strip() or None,
                attachment_url=attachment_url,
                announcement_date=sort_date or an_date,
            )
        except Exception as exc:
            logger.warning("nse_parse_error", error=str(exc), raw_keys=list(item.keys()))
            return None

    async def close(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None
            self._warmed = False
