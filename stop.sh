#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════
#  Velure — stop everything started by ./dev.sh
#  Stops the backend, the frontend, and the Docker services.
# ═══════════════════════════════════════════════════════════
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

echo "▸ Stopping backend + frontend…"
lsof -ti:8000 2>/dev/null | xargs kill 2>/dev/null || true
lsof -ti:3000 2>/dev/null | xargs kill 2>/dev/null || true
pkill -f "uvicorn main:app" 2>/dev/null || true
pkill -f "next dev" 2>/dev/null || true

echo "▸ Stopping Redis + Postgres (Docker)…"
docker compose stop redis postgres 2>/dev/null || true

echo "✓ Velure stopped."
