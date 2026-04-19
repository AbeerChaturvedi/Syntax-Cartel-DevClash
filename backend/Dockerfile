# syntax=docker/dockerfile:1.7
# ──────────────────────────────────────────────────────────────────────
#  Project Velure — Backend (multi-stage, non-root, slim runtime)
# ──────────────────────────────────────────────────────────────────────

# ─── Stage 1: builder — compile wheels with build deps ─────────────────
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc g++ libpq-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt .

# CPU-only torch first (saves ~1.7GB vs CUDA wheels), then the rest.
# We install into /install so the runtime stage can copy a clean tree.
RUN pip install --prefix=/install --no-cache-dir \
        torch==2.4.0 --index-url https://download.pytorch.org/whl/cpu && \
    pip install --prefix=/install --no-cache-dir -r requirements.txt


# ─── Stage 2: runtime — slim image, non-root, signal-aware ─────────────
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/install/lib/python3.11/site-packages:/app \
    PATH=/install/bin:$PATH \
    PIP_NO_CACHE_DIR=1

# tini = correct PID 1 (reaps zombies, forwards SIGTERM to uvicorn)
# libpq5 = runtime psycopg dependency (no -dev / no compiler)
# curl = healthcheck without pulling python urllib at every probe
RUN apt-get update && apt-get install -y --no-install-recommends \
        tini libpq5 curl && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd --system --gid 10001 velure && \
    useradd  --system --uid 10001 --gid velure --home-dir /app --shell /sbin/nologin velure

# Pull pre-built site-packages from the builder layer
COPY --from=builder /install /install

WORKDIR /app
COPY --chown=velure:velure . /app

# Writable data root for checkpoints, models, replay archives
RUN mkdir -p /app/data/models /app/data/historical /app/data/checkpoints && \
    chown -R velure:velure /app/data

USER velure

EXPOSE 8000

# Healthcheck against the FastAPI /health endpoint (defined in main.py)
HEALTHCHECK --interval=15s --timeout=5s --start-period=45s --retries=4 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

# tini → uvicorn → FastAPI app. uvloop for the event loop, no access log
# noise (we emit our own structured pipeline logs).
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--loop", "uvloop", "--no-access-log", \
     "--proxy-headers", "--forwarded-allow-ips=*"]
