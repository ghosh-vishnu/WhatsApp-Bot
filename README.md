# WhatsApp Stock Market Bot

Automated backend service that fetches corporate announcements from **NSE** and **BSE**, filters relevant updates, and posts structured messages to a **WhatsApp Channel** via the Meta Cloud API.

## Architecture

```
┌─────────────┐    ┌─────────────┐
│   NSE API   │    │   BSE API   │
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

| Layer       | Technology                     |
| ----------- | ------------------------------ |
| Framework   | FastAPI                        |
| Database    | PostgreSQL 16 + SQLAlchemy 2.0 |
| Cache       | Redis 7                        |
| Task Queue  | Celery 5 + Redis broker        |
| Scheduler   | APScheduler / Celery Beat      |
| HTTP Client | httpx (HTTP/2)                 |
| Messaging   | Meta WhatsApp Cloud API        |
| Logging     | structlog (JSON)               |

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

### Install and Run

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Create a .env file with your credentials (see Configuration below)

# 3. Start the API server
uvicorn app.main:app --reload --port 8000

# 4. Start Celery worker (separate terminal)
celery -A app.workers.celery_app:celery_app worker --queues=fetch,deliver --loglevel=info

# 5. Start Celery Beat scheduler (separate terminal)
celery -A app.workers.celery_app:celery_app beat --loglevel=info
```

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

| Variable                 | Default                      | Description                  |
| ------------------------ | ---------------------------- | ---------------------------- |
| `APP_ENV`                | `production`                 | `development` / `production` |
| `LOG_LEVEL`              | `INFO`                       | Logging verbosity            |
| `REDIS_URL`              | `redis://localhost:6379/0`   | Redis connection             |
| `CELERY_BROKER_URL`      | `redis://localhost:6379/1`   | Celery broker                |
| `FETCH_INTERVAL_SECONDS` | `300`                        | Fetch cycle (seconds)        |
| `WHATSAPP_RATE_LIMIT`    | `80`                         | Max messages per window      |
| `ALERT_WEBHOOK_URL`      | —                            | Slack/Discord webhook        |

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

## Testing

```bash
# Run tests
pytest tests/ -v

# Run with coverage
pytest tests/ -v --cov=app --cov-report=html
```

## Key Features

- **Circuit breaker** on NSE/BSE APIs to prevent cascading failures
- **Anti-bot evasion** — session cookie warming, rotating user-agents
- **Sliding-window rate limiter** (Redis-backed) for WhatsApp API
- **Dual-layer deduplication** — Redis cache + PostgreSQL unique constraint
- **Separate Celery queues** — `fetch` and `deliver` workers scale independently
- **Structured JSON logging** — ready for ELK / Datadog / CloudWatch
- **Alerting** — Slack/Discord webhooks + email on failures
- **Automatic retries** with exponential backoff on all external calls

## License

Private — All rights reserved.
