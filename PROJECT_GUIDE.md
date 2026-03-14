# Project File Guide — Kaunsi File Me Kya Hai

Har file ka kaam neeche explain kiya gaya hai.

---

## Root Files

| File | Kya Karta Hai |
|---|---|
| `.env` | Saare secrets aur config values (DB URL, WhatsApp token, etc.) yahan se load hote hain |
| `.gitignore` | Git ko batata hai ki kaunsi files track nahi karni (`.env`, `__pycache__`, etc.) |
| `requirements.txt` | Saari Python dependencies ki list — `pip install -r requirements.txt` se install hoti hain |
| `pyproject.toml` | Ruff linter, pytest, aur coverage tool ki settings |
| `README.md` | Project ka overview, setup instructions, API endpoints |

---

## `app/` — Main Application Code

| File | Kya Karta Hai |
|---|---|
| `app/config.py` | `.env` file se saari settings load karta hai (DB, Redis, WhatsApp, NSE, BSE sab kuch) |
| `app/dependencies.py` | FastAPI ke liye dependency injection — DB session aur Redis connection deta hai |
| `app/main.py` | **App ka entry point** — FastAPI app banata hai, middleware lagata hai, scheduler start karta hai, routes register karta hai |

---

## `app/api/` — API Endpoints

| File | Kya Karta Hai |
|---|---|
| `app/api/health.py` | Health check (`/health`), stats (`/stats`), announcements list (`/announcements`), manual trigger (`/trigger/fetch`, `/trigger/deliver`) — saare API routes yahan hain |

---

## `app/models/` — Database Tables

| File | Kya Karta Hai |
|---|---|
| `app/models/announcement_model.py` | `announcements` table ka SQLAlchemy model — columns: company name, title, source (NSE/BSE), content hash, delivery status, formatted message, etc. |

---

## `app/schemas/` — Data Validation

| File | Kya Karta Hai |
|---|---|
| `app/schemas/announcement_schema.py` | Pydantic schemas — incoming data validate karta hai (`AnnouncementCreate`), API response format define karta hai (`AnnouncementResponse`, `HealthResponse`) |

---

## `app/repositories/` — Database Queries

| File | Kya Karta Hai |
|---|---|
| `app/repositories/announcement_repo.py` | Saare database operations — announcement create, duplicate check (`bulk_check_hashes`), pending messages fetch, mark sent/failed, pagination, stats |

---

## `app/services/` — Business Logic (Core)

| File | Kya Karta Hai |
|---|---|
| `app/services/nse_service.py` | **NSE se announcements fetch karta hai** — session cookies maintain karta hai, anti-bot headers use karta hai, circuit breaker se wrapped hai |
| `app/services/bse_service.py` | **BSE se announcements fetch karta hai** — BSE ka JSON API call karta hai with retry logic |
| `app/services/filter_service.py` | **Filtering engine** — keyword match (dividend, bonus, split, etc.), category match, spam removal (test/duplicate/correction wale hatata hai) |
| `app/services/summary_service.py` | **WhatsApp message generate karta hai** — announcement se formatted message banata hai (company, title, source, category ke saath) |
| `app/services/whatsapp_service.py` | **WhatsApp Cloud API se message bhejta hai** — rate limiting, retry on failure, channel/newsletter support |
| `app/services/alert_service.py` | **Alert bhejta hai** jab kuch fail ho (circuit breaker trip, high failure rate) — Slack webhook ya email se notify karta hai |

---

## `app/workers/` — Background Tasks

| File | Kya Karta Hai |
|---|---|
| `app/workers/celery_app.py` | Celery app configuration — broker, queues (`fetch`, `deliver`), beat schedule (har 5 min fetch, har 30 sec deliver, har 10 min retry) |
| `app/workers/tasks.py` | **Main pipeline tasks** — `fetch_and_process_announcements` (NSE/BSE fetch → filter → deduplicate → store), `deliver_pending_messages` (WhatsApp pe bhejo), `retry_failed_messages` (failed retry karo) |
| `app/workers/scheduler.py` | APScheduler — Celery tasks ko schedule karta hai (FastAPI ke saath embedded run hota hai) |

---

## `app/utils/` — Utilities

| File | Kya Karta Hai |
|---|---|
| `app/utils/logger.py` | Structured JSON logging setup (structlog) — production me ELK/Datadog ke liye ready |
| `app/utils/security.py` | **SHA-256 hashing** (duplicate detection ke liye), rotating user-agent headers (anti-bot), Redis-backed sliding window rate limiter, text sanitizer |
| `app/utils/helpers.py` | Date parsing, text truncation, `async_retry` decorator (exponential backoff wala), list chunking |
| `app/utils/circuit_breaker.py` | **Circuit breaker pattern** — jab NSE/BSE API baar baar fail ho to calls block karta hai, recovery timeout ke baad dobara try karta hai |

---

## `infra/` — Infrastructure

| File | Kya Karta Hai |
|---|---|
| `infra/database.py` | Async PostgreSQL connection pool (SQLAlchemy 2.0) — engine, session factory, `init_db()` tables banata hai, `close_db()` cleanup |
| `infra/redis.py` | Redis connection pool — caching, deduplication, rate limiting ke liye use hota hai |

---

## `tests/` — Unit Tests

| File | Kya Test Karta Hai |
|---|---|
| `tests/conftest.py` | Shared test fixtures — sample announcements, mock settings, environment setup |
| `tests/test_filter_service.py` | Filtering engine — relevant vs irrelevant vs spam announcements check |
| `tests/test_deduplication.py` | SHA-256 hashing — same content = same hash, different content = different hash |
| `tests/test_summary_service.py` | Message generation — format, length limit, batch digest |
| `tests/test_whatsapp_service.py` | WhatsApp sender — success, API error, rate limit block (mocked HTTP + Redis) |
| `tests/test_circuit_breaker.py` | Circuit breaker — CLOSED → OPEN → HALF_OPEN transitions, reset |

---

## Data Flow (Poora Pipeline)

```
[Celery Beat — har 5 min]
        │
        ▼
  fetch_and_process_announcements (task)
        │
        ├── NSEService.fetch_announcements()  ──→  NSE API (circuit breaker protected)
        ├── BSEService.fetch_announcements()  ──→  BSE API (circuit breaker protected)
        │
        ▼
  FilterService.filter_announcements()  ──→  keyword + category + spam filter
        │
        ▼
  compute_content_hash()  ──→  SHA-256 deduplicate (Redis + PostgreSQL)
        │
        ▼
  SummaryService.generate_summary()  ──→  WhatsApp formatted message
        │
        ▼
  AnnouncementRepository.upsert()  ──→  PostgreSQL me store
        │
        ▼
  deliver_pending_messages (task — har 30 sec)
        │
        ▼
  WhatsAppService.send_channel_message()  ──→  Meta Cloud API
        │
        ▼
  Mark SENT / FAILED  ──→  retry_failed_messages (har 10 min)
```
