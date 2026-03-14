"""
Alerting service for operational notifications.
Sends alerts via webhook (Slack/Discord/PagerDuty) and optionally email
when critical events occur (circuit breaker trips, high failure rates, etc.).
"""

from __future__ import annotations

import smtplib
from email.mime.text import MIMEText
from typing import Optional

import httpx

from app.config import Settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


class AlertService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def send_alert(
        self,
        title: str,
        message: str,
        severity: str = "warning",
    ) -> None:
        """Dispatch an alert to all configured channels."""
        logger.warning(
            "alert_triggered",
            alert_title=title,
            severity=severity,
            message=message[:500],
        )

        if self._settings.ALERT_WEBHOOK_URL:
            await self._send_webhook(title, message, severity)

        if self._settings.ALERT_EMAIL_TO and self._settings.SMTP_HOST:
            await self._send_email(title, message, severity)

    async def _send_webhook(
        self, title: str, message: str, severity: str,
    ) -> None:
        """Send alert to a webhook (Slack / Discord / PagerDuty compatible)."""
        color_map = {"info": "#36a64f", "warning": "#ff9900", "critical": "#ff0000"}
        payload = {
            "text": f"[{severity.upper()}] {title}",
            "attachments": [
                {
                    "color": color_map.get(severity, "#cccccc"),
                    "title": title,
                    "text": message[:2000],
                    "fields": [
                        {"title": "Service", "value": self._settings.APP_NAME, "short": True},
                        {"title": "Severity", "value": severity.upper(), "short": True},
                    ],
                }
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(self._settings.ALERT_WEBHOOK_URL, json=payload)
                resp.raise_for_status()
                logger.info("webhook_alert_sent", title=title)
        except Exception as exc:
            logger.error("webhook_alert_failed", error=str(exc))

    async def _send_email(
        self, title: str, message: str, severity: str,
    ) -> None:
        """Send alert via SMTP email."""
        try:
            msg = MIMEText(f"Severity: {severity.upper()}\n\n{message}")
            msg["Subject"] = f"[{self._settings.APP_NAME}] [{severity.upper()}] {title}"
            msg["From"] = self._settings.SMTP_USER
            msg["To"] = self._settings.ALERT_EMAIL_TO

            with smtplib.SMTP(self._settings.SMTP_HOST, self._settings.SMTP_PORT) as server:
                server.starttls()
                server.login(self._settings.SMTP_USER, self._settings.SMTP_PASSWORD)
                server.send_message(msg)

            logger.info("email_alert_sent", title=title, to=self._settings.ALERT_EMAIL_TO)
        except Exception as exc:
            logger.error("email_alert_failed", error=str(exc))

    async def alert_circuit_open(self, breaker_name: str) -> None:
        await self.send_alert(
            title=f"Circuit Breaker OPEN: {breaker_name}",
            message=(
                f"The circuit breaker for '{breaker_name}' has tripped open. "
                f"External API calls are being blocked. "
                f"Manual investigation may be required."
            ),
            severity="critical",
        )

    async def alert_high_failure_rate(
        self, failed: int, total: int, window: str = "1h",
    ) -> None:
        rate = (failed / total * 100) if total else 0
        await self.send_alert(
            title="High Delivery Failure Rate",
            message=(
                f"{failed}/{total} messages failed in the last {window} "
                f"({rate:.1f}% failure rate). Check WhatsApp API status."
            ),
            severity="critical" if rate > 50 else "warning",
        )

    async def alert_fetch_failure(self, source: str, error: str) -> None:
        await self.send_alert(
            title=f"Fetch Failed: {source}",
            message=f"Failed to fetch announcements from {source}: {error}",
            severity="warning",
        )
