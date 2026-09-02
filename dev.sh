#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════
#  Velure — one command local dev
#  Starts Redis + Postgres (Docker) and runs the FastAPI backend
#  and the Next.js frontend with hot reload, all from one terminal.
#  Press Ctrl+C to stop the backend and frontend.
#  Run ./stop.sh for a full stop (including the Docker services).
# ═══════════════════════════════════════════════════════════
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

echo "▸ Starting Redis + Postgres (Docker)…"
docker compose up -d redis postgres

# Backend virtualenv + deps on first run
if [ ! -x backend/venv/bin/python ]; then
  echo "▸ Creating backend virtualenv (first run)…"
  python3 -m venv backend/venv
  backend/venv/bin/pip install -q -r backend/requirements.txt
fi

# Frontend deps on first run
if [ ! -d frontend/node_modules ]; then
  echo "▸ Installing frontend dependencies (first run)…"
  ( cd frontend && npm install )
fi

# Frontend env on first run
if [ ! -f frontend/.env.local ]; then
  printf 'NEXT_PUBLIC_API_URL=http://localhost:8000\nNEXT_PUBLIC_WS_URL=ws://localhost:8000/ws/dashboard\n' > frontend/.env.local
fi

echo "▸ Starting backend (:8000) and frontend (:3000)…"
( cd backend && exec venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000 --loop asyncio --log-level warning ) &
BACK=$!
( cd frontend && exec npm run dev ) &
FRONT=$!

cleanup() {
  echo
  echo "▸ Stopping backend + frontend…"
  kill "$BACK" "$FRONT" 2>/dev/null || true
  wait 2>/dev/null || true
  echo "  Docker services are still running. Run ./stop.sh for a full stop."
}
trap cleanup INT TERM

echo ""
echo "  ✔ Dashboard  →  http://localhost:3000"
echo "  ✔ Backend    →  http://localhost:8000   (health: /health)"
echo "  Press Ctrl+C to stop."
echo ""
wait
