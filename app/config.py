"""
Application configuration loaded from environment variables.
All secrets and tunable parameters are centralized here.
"""

from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── App ──────────────────────────────────────────────────────────────
    APP_NAME: str = "whatsapp-stock-bot"
    APP_ENV: str = Field(default="production", pattern="^(development|staging|production)$")
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    SECRET_KEY: str = Field(..., min_length=32)

    # ── Database ─────────────────────────────────────────────────────────
    DATABASE_URL: str = Field(..., description="PostgreSQL connection string")
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800

    # ── Redis ────────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_MAX_CONNECTIONS: int = 50
    REDIS_CACHE_TTL: int = 300

    # ── Celery ───────────────────────────────────────────────────────────
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"
    CELERY_TASK_SOFT_TIME_LIMIT: int = 120
    CELERY_TASK_TIME_LIMIT: int = 180

    # ── WhatsApp Cloud API ───────────────────────────────────────────────
    WHATSAPP_API_VERSION: str = "v21.0"
    WHATSAPP_PHONE_NUMBER_ID: str = Field(..., min_length=1)
    WHATSAPP_ACCESS_TOKEN: str = Field(..., min_length=1)
    WHATSAPP_CHANNEL_ID: str = Field(default="", description="WhatsApp Channel ID for newsletter")
    WHATSAPP_RATE_LIMIT: int = 80
    WHATSAPP_RATE_WINDOW: int = 60

    # ── NSE / BSE ────────────────────────────────────────────────────────
    NSE_BASE_URL: str = "https://www.nseindia.com"
    BSE_BASE_URL: str = "https://api.bseindia.com/BseIndiaAPI/api"
    FETCH_INTERVAL_SECONDS: int = 300
    REQUEST_TIMEOUT: int = 30
    MAX_RETRIES: int = 3
    RETRY_BACKOFF_FACTOR: float = 1.5

    # ── Circuit Breaker ──────────────────────────────────────────────────
    CB_FAILURE_THRESHOLD: int = 5
    CB_RECOVERY_TIMEOUT: int = 60
    CB_HALF_OPEN_MAX_CALLS: int = 3

    # ── Filtering ────────────────────────────────────────────────────────
    FILTER_KEYWORDS: List[str] = Field(default_factory=lambda: [
        # Common corporate actions
        "dividend", "bonus", "split", "buyback", "merger", "acquisition",
        "rights issue", "ipo", "delisting", "board meeting", "agm",
        "quarterly results", "annual results", "financial results",
        "stock split", "restructuring", "insider trading", "shareholding",
        "credit rating", "debenture", "preferential allotment",
        # NSE announcement subjects
        "general updates", "updates", "outcome of board",
        "trading window", "order", "contract", "appointment",
        "resignation", "investor meet", "investor presentation",
        "newspaper publication", "esop", "esos", "esps",
        "offer for sale", "amalgamation", "disclosure",
        "intimation", "regulation", "nclt", "letter of offer",
        "fund raising", "allotment", "listing", "change in director",
        "analyst", "press release", "corporate action",
    ])
    FILTER_CATEGORIES: List[str] = Field(default_factory=lambda: [
        # BSE categories
        "Corp. Action", "Result", "Board Meeting", "AGM/EGM",
        "Insider Trading", "Company Update", "Shareholding",
        # NSE industry categories (smIndustry field)
        "Pharmaceuticals", "Finance", "Power", "Chemicals",
        "Engineering", "Textiles", "Food", "Petrochemicals",
        "Computers", "Software", "Banking", "Automobiles",
        "Cement", "Steel", "Mining", "Telecom", "Infrastructure",
        "Insurance", "Real Estate", "NBFC", "Media",
    ])
    SPAM_KEYWORDS: List[str] = Field(default_factory=lambda: [
        "duplicate", "test", "correction", "revised",
    ])

    # ── LLM (OpenAI) for summary enrichment ─────────────────────────────
    LLM_ENABLED: bool = False
    OPENAI_API_KEY: str = ""
    LLM_MODEL: str = "gpt-4o-mini"
    LLM_TIMEOUT: int = 15
    LLM_MAX_RETRIES: int = 2

    # ── Alerting ─────────────────────────────────────────────────────────
    ALERT_WEBHOOK_URL: str = ""
    ALERT_EMAIL_TO: str = ""
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""

    @field_validator("LOG_LEVEL")
    @classmethod
    def _validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {allowed}")
        return upper

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
    }

    def model_post_init(self, __context) -> None:
        """Ensure DEBUG is off in production."""
        if self.APP_ENV == "production" and self.DEBUG:
            raise ValueError("DEBUG must be False when APP_ENV=production")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
