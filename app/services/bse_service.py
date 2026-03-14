"""
BSE (Bombay Stock Exchange) announcement fetcher.

BSE provides a more conventional JSON API that is less aggressive with bot blocking.
"""

from __future__ import annotations

from typing import Optional

import httpx

from app.config import Settings
from app.schemas.announcement_schema import AnnouncementCreate, SourceEnum
from app.utils.circuit_breaker import CircuitBreaker
from app.utils.helpers import async_retry, parse_datetime
from app.utils.logger import get_logger
from app.utils.security import get_rotating_headers, sanitize_text

logger = get_logger(__name__)


class BSEService:
    """Fetches corporate announcements from BSE India."""

    ANNOUNCEMENTS_ENDPOINT = "/AnnSubCategoryGetData/w"

    def __init__(self, settings: Settings, circuit_breaker: CircuitBreaker) -> None:
        self._settings = settings
        self._cb = circuit_breaker
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._settings.BSE_BASE_URL,
                timeout=httpx.Timeout(self._settings.REQUEST_TIMEOUT),
                follow_redirects=True,
            )
        return self._client

    @async_retry(max_attempts=3, backoff_factor=1.5, exceptions=(httpx.HTTPError, Exception))
    async def _fetch_page(self, page: int = 1) -> list[dict]:
        async def _do_fetch() -> list[dict]:
            client = await self._get_client()
            headers = get_rotating_headers()
            headers["Referer"] = "https://www.bseindia.com/corporates/ann.html"
            headers["Origin"] = "https://www.bseindia.com"

            params = {
                "pageno": str(page),
                "strCat": "-1",
                "strPrevDate": "",
                "strScrip": "",
                "strSearch": "P",
                "strToDate": "",
                "strType": "C",
            }
            resp = await client.get(
                self.ANNOUNCEMENTS_ENDPOINT,
                headers=headers,
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict):
                return data.get("Table", [])
            return data if isinstance(data, list) else []

        return await self._cb.call(_do_fetch)

    async def fetch_announcements(self, pages: int = 2) -> list[AnnouncementCreate]:
        all_announcements: list[AnnouncementCreate] = []

        for page_num in range(1, pages + 1):
            try:
                raw = await self._fetch_page(page=page_num)
                parsed = [self._parse(item) for item in raw if item]
                all_announcements.extend([a for a in parsed if a is not None])
                logger.info(
                    "bse_page_fetched",
                    page=page_num,
                    count=len(raw),
                    parsed=len(parsed),
                )
            except Exception as exc:
                logger.error("bse_page_fetch_error", page=page_num, error=str(exc))
                break

        logger.info("bse_fetch_complete", total=len(all_announcements))
        return all_announcements

    def _parse(self, item: dict) -> Optional[AnnouncementCreate]:
        try:
            company_name = sanitize_text(
                item.get("SLONGNAME", "") or item.get("SCRIP_CD", "") or ""
            )
            headline = sanitize_text(item.get("NEWSSUB", "") or "")

            if not company_name or not headline:
                return None

            news_body = sanitize_text(item.get("NEWS_DT", "") or "")
            category = item.get("CATEGORYNAME", "") or item.get("SUBCATNAME", "") or ""
            scrip_code = item.get("SCRIP_CD", "")
            news_id = item.get("NEWSID", "")

            dt_str = item.get("NEWS_DT") or item.get("DT_TM")
            an_date = parse_datetime(dt_str)

            attachment_url = None
            attachment = item.get("ATTACHMENTNAME", "")
            if attachment:
                attachment_url = (
                    f"https://www.bseindia.com/xml-data/corpfiling/AttachLive/{attachment}"
                )

            return AnnouncementCreate(
                source=SourceEnum.BSE,
                source_id=str(news_id) if news_id else None,
                company_name=company_name,
                symbol=str(scrip_code).strip() or None,
                title=headline,
                description=news_body or None,
                category=category.strip() or None,
                attachment_url=attachment_url,
                announcement_date=an_date,
            )
        except Exception as exc:
            logger.warning("bse_parse_error", error=str(exc), raw_keys=list(item.keys()))
            return None

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
