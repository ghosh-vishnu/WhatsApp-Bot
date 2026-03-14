"""
WhatsApp Cloud API integration for sending channel messages.

Supports:
  - Text messages to WhatsApp Channels (newsletter)
  - Rate limiting via Redis sliding window
  - Automatic retries with exponential backoff
  - Template messages for high-scale delivery
"""

from __future__ import annotations

from typing import Optional

import httpx
import redis.asyncio as aioredis

from app.config import Settings
from app.utils.helpers import async_retry
from app.utils.logger import get_logger
from app.utils.security import RateLimiter

logger = get_logger(__name__)


class WhatsAppSendError(Exception):
    """Raised when a WhatsApp API call fails. Not retried (client errors)."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"WhatsApp API error {status_code}: {detail}")


class WhatsAppServerError(WhatsAppSendError):
    """Raised on 5xx server errors. Retried automatically."""
    pass


class WhatsAppService:
    def __init__(self, settings: Settings, redis: aioredis.Redis) -> None:
        self._settings = settings
        self._base_url = (
            f"https://graph.facebook.com/{settings.WHATSAPP_API_VERSION}"
            f"/{settings.WHATSAPP_PHONE_NUMBER_ID}"
        )
        self._headers = {
            "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        }
        self._rate_limiter = RateLimiter(
            redis=redis,
            key_prefix="wa_ratelimit",
            max_requests=settings.WHATSAPP_RATE_LIMIT,
            window_seconds=settings.WHATSAPP_RATE_WINDOW,
        )
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(30),
                follow_redirects=True,
            )
        return self._client

    @async_retry(max_attempts=3, backoff_factor=2.0, exceptions=(httpx.HTTPError, WhatsAppServerError))
    async def send_channel_message(self, message: str) -> dict:
        """
        Send a text message to the WhatsApp Channel / Newsletter.

        Uses the newsletter API endpoint when WHATSAPP_CHANNEL_ID is set,
        otherwise falls back to standard messaging endpoint.
        """
        if not await self._rate_limiter.is_allowed("whatsapp_send"):
            remaining = await self._rate_limiter.get_remaining("whatsapp_send")
            logger.warning("whatsapp_rate_limited", remaining=remaining)
            raise WhatsAppSendError(429, "Rate limit exceeded")

        client = await self._get_client()

        if self._settings.WHATSAPP_CHANNEL_ID:
            return await self._send_newsletter_message(client, message)
        else:
            return await self._send_text_message(client, message)

    async def _send_newsletter_message(self, client: httpx.AsyncClient, message: str) -> dict:
        """Send a message to a WhatsApp Newsletter/Channel."""
        url = (
            f"https://graph.facebook.com/{self._settings.WHATSAPP_API_VERSION}"
            f"/{self._settings.WHATSAPP_CHANNEL_ID}/messages"
        )
        payload = {
            "messaging_product": "whatsapp",
            "type": "text",
            "text": {"body": message},
        }

        resp = await client.post(url, json=payload, headers=self._headers)

        if resp.status_code >= 500:
            error_detail = resp.text[:500]
            logger.error("whatsapp_newsletter_send_5xx", status=resp.status_code, detail=error_detail)
            raise WhatsAppServerError(resp.status_code, error_detail)

        if resp.status_code >= 400:
            error_detail = resp.text[:500]
            logger.error("whatsapp_newsletter_send_failed", status=resp.status_code, detail=error_detail)
            raise WhatsAppSendError(resp.status_code, error_detail)

        data = resp.json()
        msg_id = ""
        if "messages" in data and data["messages"]:
            msg_id = data["messages"][0].get("id", "")

        logger.info("whatsapp_newsletter_sent", message_id=msg_id)
        return {"message_id": msg_id, "status": "sent"}

    async def _send_text_message(self, client: httpx.AsyncClient, message: str) -> dict:
        """
        Fallback: send a standard WhatsApp text message.
        Useful for testing or direct messaging.
        """
        url = f"{self._base_url}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "type": "text",
            "text": {"body": message, "preview_url": False},
        }

        resp = await client.post(url, json=payload, headers=self._headers)

        if resp.status_code >= 500:
            error_detail = resp.text[:500]
            logger.error("whatsapp_send_5xx", status=resp.status_code, detail=error_detail)
            raise WhatsAppServerError(resp.status_code, error_detail)

        if resp.status_code >= 400:
            error_detail = resp.text[:500]
            logger.error("whatsapp_send_failed", status=resp.status_code, detail=error_detail)
            raise WhatsAppSendError(resp.status_code, error_detail)

        data = resp.json()
        msg_id = ""
        if "messages" in data and data["messages"]:
            msg_id = data["messages"][0].get("id", "")

        logger.info("whatsapp_message_sent", message_id=msg_id)
        return {"message_id": msg_id, "status": "sent"}

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
