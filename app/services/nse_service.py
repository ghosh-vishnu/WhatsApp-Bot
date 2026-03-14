"""
NSE (National Stock Exchange) announcement fetcher.

NSE aggressively blocks bots, so this service:
  - Maintains a session with cookies from the homepage
  - Uses rotating user-agents
  - Respects rate limits
  - Wraps calls in a circuit breaker
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import httpx

from app.config import Settings
from app.schemas.announcement_schema import AnnouncementCreate, SourceEnum
from app.utils.circuit_breaker import CircuitBreaker
from app.utils.helpers import async_retry, parse_datetime
from app.utils.logger import get_logger
from app.utils.security import get_rotating_headers, sanitize_text

logger = get_logger(__name__)


class NSEService:
    """Fetches corporate announcements from NSE India."""

    ANNOUNCEMENTS_ENDPOINT = "/api/corporate-announcements"
    HOMEPAGE = "https://www.nseindia.com"

    def __init__(self, settings: Settings, circuit_breaker: CircuitBreaker) -> None:
        self._settings = settings
        self._cb = circuit_breaker
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Create or reuse an HTTP client with NSE session cookies."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._settings.NSE_BASE_URL,
                timeout=httpx.Timeout(self._settings.REQUEST_TIMEOUT),
                follow_redirects=True,
                http2=True,
            )
            await self._warm_session()
        return self._client

    async def _warm_session(self) -> None:
        """Hit the NSE homepage to obtain session cookies before hitting APIs."""
        try:
            headers = get_rotating_headers()
            headers["Referer"] = self.HOMEPAGE
            resp = await self._client.get("/", headers=headers)  # type: ignore[union-attr]
            resp.raise_for_status()
            logger.info("nse_session_warmed", status=resp.status_code)
        except Exception as exc:
            logger.warning("nse_session_warm_failed", error=str(exc))

    @async_retry(max_attempts=3, backoff_factor=2.0, exceptions=(httpx.HTTPError, Exception))
    async def _fetch_page(self, index: int = 0, size: int = 50) -> list[dict]:
        """Fetch a single page of announcements from NSE."""

        async def _do_fetch() -> list[dict]:
            client = await self._get_client()
            headers = get_rotating_headers()
            headers["Referer"] = f"{self.HOMEPAGE}/companies-listing/corporate-filings-announcements"

            params = {"index": str(index), "fo_sec": "", "from_date": "", "to_date": ""}
            resp = await client.get(
                self.ANNOUNCEMENTS_ENDPOINT,
                headers=headers,
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else []

        return await self._cb.call(_do_fetch)

    async def fetch_announcements(self, pages: int = 2) -> list[AnnouncementCreate]:
        """Fetch latest announcements from NSE across multiple pages."""
        all_announcements: list[AnnouncementCreate] = []

        for page_idx in range(pages):
            try:
                raw = await self._fetch_page(index=page_idx * 50)
                parsed = [self._parse(item) for item in raw if item]
                all_announcements.extend([a for a in parsed if a is not None])
                logger.info(
                    "nse_page_fetched",
                    page=page_idx,
                    count=len(raw),
                    parsed=len(parsed),
                )
            except Exception as exc:
                logger.error("nse_page_fetch_error", page=page_idx, error=str(exc))
                break

        logger.info("nse_fetch_complete", total=len(all_announcements))
        return all_announcements

    def _parse(self, item: dict) -> Optional[AnnouncementCreate]:
        try:
            company = sanitize_text(item.get("an_dt", "") or item.get("attchmntFile", "") or "")
            symbol = item.get("symbol", "") or ""
            subject = sanitize_text(item.get("desc", "") or "")
            company_name = sanitize_text(item.get("sm_name", "") or company)

            if not company_name or not subject:
                return None

            category = item.get("smIndustry", "") or item.get("attchmntText", "") or ""
            an_date = parse_datetime(item.get("an_dt"))
            sort_date = parse_datetime(item.get("sort_date"))
            attachment = item.get("attchmntFile", "")

            attachment_url = None
            if attachment:
                attachment_url = f"{self._settings.NSE_BASE_URL}/corporate/content/{attachment}"

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
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
