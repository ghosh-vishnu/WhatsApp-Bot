"""
Tests for the WhatsApp service with mocked HTTP and Redis.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.whatsapp_service import WhatsAppSendError, WhatsAppServerError, WhatsAppService


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.zremrangebyscore = AsyncMock(return_value=0)
    redis.zcard = AsyncMock(return_value=0)
    redis.zadd = AsyncMock(return_value=1)
    redis.expire = AsyncMock(return_value=True)

    pipe = AsyncMock()
    pipe.zremrangebyscore = MagicMock(return_value=pipe)
    pipe.zcard = MagicMock(return_value=pipe)
    pipe.zadd = MagicMock(return_value=pipe)
    pipe.expire = MagicMock(return_value=pipe)
    pipe.execute = AsyncMock(return_value=[0, 0, 1, True])
    redis.pipeline = MagicMock(return_value=pipe)

    return redis


@pytest.fixture
def wa_service(settings, mock_redis):
    return WhatsAppService(settings, mock_redis)


class TestWhatsAppService:
    @pytest.mark.asyncio
    async def test_send_message_success(self, wa_service):
        mock_response = httpx.Response(
            200,
            json={"messages": [{"id": "wamid.abc123"}]},
            request=httpx.Request("POST", "https://example.com"),
        )

        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock, return_value=mock_response):
            result = await wa_service.send_channel_message("Test message")
            assert result["status"] == "sent"

    @pytest.mark.asyncio
    async def test_send_message_api_error(self, wa_service):
        mock_response = httpx.Response(
            400,
            json={"error": {"message": "Invalid token"}},
            request=httpx.Request("POST", "https://example.com"),
        )

        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock, return_value=mock_response):
            with pytest.raises(WhatsAppSendError) as exc_info:
                await wa_service.send_channel_message("Test message")
            assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_rate_limit_blocks_send(self, wa_service, mock_redis):
        pipe = mock_redis.pipeline()
        pipe.execute = AsyncMock(return_value=[0, 100, 1, True])

        with pytest.raises(WhatsAppSendError) as exc_info:
            await wa_service.send_channel_message("Test message")
        assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_close_client(self, wa_service):
        wa_service._client = AsyncMock()
        wa_service._client.is_closed = False
        await wa_service.close()
        wa_service._client.aclose.assert_called_once()
