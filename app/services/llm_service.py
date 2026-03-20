"""
LLM service for analyzing corporate announcements.
Uses OpenAI API to generate SUMMARY, IMPACT, STRENGTH, MARKET VIEW.
Production-ready: retries, timeout, graceful fallback.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.config import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class LLMAnalysis:
    summary: str
    impact: str  # Bullish | Bearish | Neutral
    strength: int  # 1-10
    market_view: str


_ANALYSIS_PROMPT = """You are a stock market analyst. Analyze this Indian stock exchange (NSE/BSE) corporate announcement and return JSON only.

Company: {company}
Category: {category}
Title: {title}
Description: {description}

Return a JSON object with exactly these keys (no markdown, no extra text):
- "summary": 1-2 sentence plain-English summary for retail investors (max 150 chars)
- "impact": one of "Bullish", "Bearish", "Neutral"
- "strength": integer 1-10 (how significant for stock price: 1=minor, 10=major)
- "market_view": one short phrase e.g. "Positive for short term" or "Monitor for updates" (max 50 chars)

JSON:"""


class LLMService:
    """OpenAI-based analysis for corporate announcements."""

    def __init__(self) -> None:
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                from openai import AsyncOpenAI
                settings = get_settings()
                self._client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            except ImportError:
                raise RuntimeError("openai package not installed")
        return self._client

    def _parse_response(self, raw: str) -> LLMAnalysis | None:
        """Parse LLM response into LLMAnalysis. Returns None on parse error."""
        try:
            # Strip markdown code blocks if present
            text = raw.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            text = text.strip()
            data = json.loads(text)

            impact = str(data.get("impact", "Neutral")).strip()
            if impact not in ("Bullish", "Bearish", "Neutral"):
                impact = "Neutral"

            strength = int(data.get("strength", 5))
            strength = max(1, min(10, strength))

            summary = str(data.get("summary", "")).strip() or "Corporate announcement update."
            market_view = str(data.get("market_view", "Relevant for investors")).strip() or "Relevant for investors"

            return LLMAnalysis(summary=summary, impact=impact, strength=strength, market_view=market_view)
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.warning("llm_parse_failed", error=str(e)[:100], raw=raw[:200])
            return None

    async def analyze_announcement(
        self,
        company: str,
        title: str,
        description: str,
        category: str,
    ) -> LLMAnalysis | None:
        """
        Analyze announcement via OpenAI. Returns None on failure (caller should fallback).
        """
        settings = get_settings()
        if not settings.OPENAI_API_KEY or not settings.LLM_ENABLED:
            return None

        # Truncate to avoid token overflow
        desc = (description or "")[:1500]
        prompt = _ANALYSIS_PROMPT.format(
            company=company[:200],
            category=(category or "")[:100],
            title=title[:800],
            description=desc,
        )

        last_error: Exception | None = None
        for attempt in range(settings.LLM_MAX_RETRIES + 1):
            try:
                client = self._get_client()
                response = await client.chat.completions.create(
                    model=settings.LLM_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2,
                    max_tokens=300,
                    timeout=settings.LLM_TIMEOUT,
                )
                content = response.choices[0].message.content
                if content:
                    return self._parse_response(content)
                logger.warning("llm_empty_response")
                return None
            except Exception as e:
                last_error = e
                logger.warning(
                    "llm_request_failed",
                    attempt=attempt + 1,
                    error=str(e)[:150],
                )
                if attempt < settings.LLM_MAX_RETRIES:
                    continue
                break

        logger.error("llm_exhausted_retries", error=str(last_error)[:200])
        return None
