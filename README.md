# WhatsApp Stock Market Bot

Automated backend service that fetches corporate announcements from **NSE** and **BSE**, filters relevant updates, and posts structured messages to a **WhatsApp Channel** via the Meta Cloud API.

## Architecture

```
┌─────────────┐    ┌─────────────┐
│   NSE API   │    │   BSE API   │
│ (curl_cffi) │    │   (httpx)   │
└──────┬──────┘    └──────┬──────┘
       │   Circuit Breaker     │
       └──────────┬───────────┘
                  ▼
        ┌─────────────────┐
        │  Filter Engine  │  keyword + category + spam
        └────────┬────────┘
                 ▼
        ┌─────────────────┐
        │  Deduplication   │  SHA-256 hash → Redis + PostgreSQL
        └────────┬────────┘
                 ▼
        ┌─────────────────┐
        │ Summary Builder  │  WhatsApp-formatted messages
        └────────┬────────┘
                 ▼
        ┌─────────────────┐
        │ WhatsApp Sender  │  Meta Cloud API + rate limiter
        └─────────────────┘
```

## Tech Stack

| Layer       | Technology                                  |
| ----------- | ------------------------------------------- |
| Framework   | FastAPI                                     |
| Database    | PostgreSQL 16 + SQLAlchemy 2.0              |
| Cache       | Redis 7                                     |
| Task Queue  | Celery 5 + Redis broker                     |
| Scheduler   | APScheduler / Celery Beat                   |
| HTTP Client | httpx (BSE) + curl_cffi (NSE, TLS spoofing) |
| Messaging   | Meta WhatsApp Cloud API                     |
| Logging     | structlog (JSON)                            |

## Project Structure

```
app/
├── api/               # FastAPI route handlers
├── models/            # SQLAlchemy ORM models
├── schemas/           # Pydantic validation schemas
├── repositories/      # Database access layer
├── services/          # Business logic (NSE, BSE, filter, summary, WhatsApp, alerting)
├── workers/           # Celery tasks + scheduler
├── utils/             # Logger, circuit breaker, security, helpers
├── config.py          # Centralized settings from env vars
├── dependencies.py    # FastAPI dependency injection
└── main.py            # App entry point

infra/
├── database.py        # Async PostgreSQL engine
└── redis.py           # Redis connection pool

tests/                 # Unit tests
```

## Setup

### Prerequisites

- Python 3.11+
- PostgreSQL 16
- Redis 7

### Option A: Docker (Production / VPS)

```bash
# 1. Copy environment template and fill in your values
cp .env.example .env
# Edit .env with SECRET_KEY, POSTGRES_PASSWORD, WHATSAPP_*, etc.

# 2. Build and run
docker compose build
docker compose up -d

# Optional: Celery Flower monitoring
docker compose --profile flower up -d
```

Access the API at `http://localhost:8000`. Use `X-API-Key: <SECRET_KEY>` for protected endpoints.

### VPS Deployment

1. Copy the project to your VPS (e.g. via `git clone` or `scp`).
2. Create `.env` from `.env.example` and set all required secrets.
3. Run `docker compose up -d` (ensures PostgreSQL, Redis, API, Celery worker, and beat start with health checks).
4. Put a reverse proxy (Nginx/Caddy) in front of the API for TLS and optional rate limiting.

### Option B: Local Development

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Create a .env file with your credentials (see Configuration below)

# 3. Start the API server
uvicorn app.main:app --reload --port 8000

# 4. Start Celery worker (separate terminal)
celery -A app.workers.celery_app:celery_app worker --queues=fetch,deliver --loglevel=info

# 5. Start Celery Beat scheduler (separate terminal)
# Windows: add -s "$env:TEMP\celerybeat-schedule" to avoid permission errors
celery -A app.workers.celery_app:celery_app beat --loglevel=info -s "$env:TEMP\celerybeat-schedule"
```

> **Windows note:** The Celery worker uses the `solo` pool automatically. For Celery Beat on Windows, add `-s "$env:TEMP\celerybeat-schedule"` so the schedule file is written to Temp (avoids permission denied).

## Configuration

Create a `.env` file in the project root. All settings are defined in `app/config.py`.

### Required Variables

| Variable                   | Description                      |
| -------------------------- | -------------------------------- |
| `SECRET_KEY`               | App secret (min 32 chars)        |
| `DATABASE_URL`             | PostgreSQL connection string     |
| `WHATSAPP_PHONE_NUMBER_ID` | Meta phone number ID             |
| `WHATSAPP_ACCESS_TOKEN`    | Meta permanent access token      |
| `WHATSAPP_CHANNEL_ID`      | WhatsApp Channel / Newsletter ID |

### Optional Variables

| Variable                 | Default                    | Description                  |
| ------------------------ | -------------------------- | ---------------------------- |
| `APP_ENV`                | `production`               | `development` / `production` |
| `LOG_LEVEL`              | `INFO`                     | Logging verbosity            |
| `REDIS_URL`              | `redis://localhost:6379/0` | Redis connection             |
| `CELERY_BROKER_URL`      | `redis://localhost:6379/1` | Celery broker                |
| `FETCH_INTERVAL_SECONDS` | `60`                       | Fetch cycle (seconds)        |
| `WHATSAPP_RATE_LIMIT`    | `80`                       | Max messages per window      |
| `LLM_ENABLED`            | `false`                    | Use OpenAI for SUMMARY/IMPACT |
| `OPENAI_API_KEY`         | —                          | OpenAI API key (when LLM enabled) |
| `LLM_MODEL`              | `gpt-4o-mini`              | OpenAI model                 |
| `ALERT_WEBHOOK_URL`      | —                          | Slack/Discord webhook        |

## API Endpoints

| Method | Path                      | Description             |
| ------ | ------------------------- | ----------------------- |
| GET    | `/api/v1/health`          | Full health check       |
| GET    | `/api/v1/health/ready`    | Readiness probe         |
| GET    | `/api/v1/health/live`     | Liveness probe          |
| GET    | `/api/v1/stats`           | Processing statistics   |
| GET    | `/api/v1/announcements`   | List announcements      |
| POST   | `/api/v1/trigger/fetch`   | Manual fetch trigger    |
| POST   | `/api/v1/trigger/deliver` | Manual delivery trigger |

## Data Sources

| Exchange | API Endpoint                                        | Method     | Items per cycle |
| -------- | --------------------------------------------------- | ---------- | --------------- |
| BSE      | `api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w` | httpx      | ~100 (2 pages)  |
| NSE      | `nseindia.com/api/corporate-announcements`          | curl_cffi  | ~80 (4 segments: equities, sme, debt, mf) |

NSE requires browser TLS fingerprint impersonation (via `curl_cffi`) to bypass Cloudflare bot detection. Session cookies are obtained by warming the homepage before API calls.

## Testing

```bash
# Run tests
pytest tests/ -v

# Run with coverage
pytest tests/ -v --cov=app --cov-report=html
```

## LLM Summary (Optional)

Set `LLM_ENABLED=true` and `OPENAI_API_KEY=sk-...` to use OpenAI for richer SUMMARY, IMPACT, STRENGTH, and MARKET VIEW. Falls back to rule-based logic if the API fails or is disabled. Uses `gpt-4o-mini` by default (~$0.15/1M input tokens).

## Key Features

- **Dual exchange support** — NSE + BSE corporate announcements fetched every 60 seconds
- **TLS fingerprint impersonation** — `curl_cffi` spoofs real browser (Chrome/Edge/Safari) to bypass NSE's Cloudflare
- **Circuit breaker** on NSE/BSE APIs to prevent cascading failures
- **Sliding-window rate limiter** (Redis-backed) for WhatsApp API
- **Dual-layer deduplication** — Redis cache + PostgreSQL unique constraint
- **Separate Celery queues** — `fetch` and `deliver` workers scale independently
- **Windows compatible** — auto-detects OS and uses `solo` pool on Windows
- **Structured JSON logging** — ready for ELK / Datadog / CloudWatch
- **Alerting** — Slack/Discord webhooks + email on failures
- **Automatic retries** with exponential backoff on all external calls

## Troubleshooting

### New data stopped appearing in the database

1. **Celery Beat crash** — If `wsbot-celery-beat` shows `Restarting`, it was likely failing due to `Permission denied: celerybeat-schedule`. The fix uses `/tmp` for the schedule file. Redeploy:
   ```bash
   docker compose up -d celery-beat
   ```

2. **Manual fetch** — To force an immediate fetch and verify the pipeline:
   ```bash
   curl -X POST "http://your-api/api/v1/trigger/fetch" -H "X-API-Key: YOUR_SECRET_KEY"
   ```

3. **Check Celery worker logs** — NSE/BSE or WhatsApp errors will appear here:
   ```bash
   docker logs wsbot-celery-worker --tail 100
   ```

4. **Circuit breaker** — After 5 consecutive NSE or BSE failures, the circuit opens and no fetches run for 60 seconds. Check logs for `nse_circuit_open` or `bse_circuit_open`.

## License

Private — All rights reserved.
