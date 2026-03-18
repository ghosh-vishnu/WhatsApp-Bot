# ── Stage 1: Builder ─────────────────────────────────────────────────
FROM python:3.11-slim as builder

WORKDIR /build

# Install build dependencies for native extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libcurl4-openssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Create production requirements (exclude dev/test)
RUN pip install --no-cache-dir --upgrade pip

COPY requirements-prod.txt .
RUN pip install --no-cache-dir --user -r requirements-prod.txt

# ── Stage 2: Runtime ────────────────────────────────────────────────
FROM python:3.11-slim as runtime

WORKDIR /app

# Runtime deps only (curl_cffi may need libcurl)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libcurl4 \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd --gid 1000 appgroup \
    && useradd --uid 1000 --gid appgroup --shell /bin/bash --create-home appuser

# Copy Python packages from builder
COPY --from=builder /root/.local /home/appuser/.local
ENV PATH=/home/appuser/.local/bin:$PATH

# Copy application code
COPY --chown=appuser:appgroup app/ ./app/
COPY --chown=appuser:appgroup infra/ ./infra/
COPY --chown=appuser:appgroup pyproject.toml ./

USER appuser

# Default: run API
EXPOSE 8000
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

CMD ["gunicorn", "app.main:app", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "2", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--access-logfile", "-", \
     "--capture-output", \
     "--enable-stdio-inheritance"]
