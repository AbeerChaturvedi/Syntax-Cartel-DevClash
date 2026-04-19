"""
Project Velure — FastAPI Backend (Production-Grade)
Real-Time Financial Crisis Early Warning System
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from utils.config import CORS_ORIGINS, API_KEY, RATE_LIMIT_PER_MINUTE
from utils.middleware import SecurityMiddleware

from lifecycle import lifespan

from Routes.system import router as system_router
from Routes.models import router as models_router
from Routes.stress import router as stress_router
from Routes.websocket import router as websocket_router
from Routes.news import router as news_router
from Routes.portfolio import router as portfolio_router
from Routes.historical import router as historical_router
from Routes.backtest import router as backtest_router
from Routes.replay import router as replay_router
from Routes.audit import router as audit_router
from Routes.Speed import router as speed_router

# ── FastAPI App ──────────────────────────────────────────────────────
app = FastAPI(
    title="Project Velure — Crisis Early Warning System",
    description="Real-time financial crisis detection using ML ensemble (IF + LSTM + CISS + Merton + VaR)",
    version="3.0.0",
    lifespan=lifespan,
)

# CORS — configurable origins.
# Production assertion: if VELURE_API_KEY is set we treat this as prod and
# refuse a wildcard origin.
_cors_origins = [o.strip() for o in CORS_ORIGINS.split(",")] if CORS_ORIGINS != "*" else ["*"]
if API_KEY and "*" in _cors_origins:
    raise RuntimeError(
        "Refusing to start: CORS_ORIGINS='*' with an API key set is unsafe. "
        "Set CORS_ORIGINS to an explicit comma-separated list of HTTPS origins."
    )
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting + optional API key auth
app.add_middleware(SecurityMiddleware, rate_limit=RATE_LIMIT_PER_MINUTE, api_key=API_KEY)

# ── Routers ──────────────────────────────────────────────────────
app.include_router(system_router)
app.include_router(models_router)
app.include_router(stress_router)
app.include_router(websocket_router)
app.include_router(news_router)
app.include_router(portfolio_router)
app.include_router(historical_router)
app.include_router(backtest_router)
app.include_router(replay_router)
app.include_router(audit_router)
app.include_router(speed_router)
