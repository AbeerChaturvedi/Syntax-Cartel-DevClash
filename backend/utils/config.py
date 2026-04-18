"""
Project Velure — Centralized Configuration
All tunable parameters in one place. Environment variables override defaults.
"""
import os
from dotenv import load_dotenv

load_dotenv()


def _env(key: str, default, cast=str):
    val = os.getenv(key)
    if val is None:
        return default
    try:
        return cast(val)
    except (ValueError, TypeError):
        return default


# ── Infrastructure ──────────────────────────────────────────────────
REDIS_URL = _env("REDIS_URL", f"redis://{_env('REDIS_HOST', 'localhost')}:{_env('REDIS_PORT', 6379, int)}")
POSTGRES_DSN = _env(
    "DATABASE_URL",
    f"postgresql://{_env('POSTGRES_USER', 'velure')}:{_env('POSTGRES_PASSWORD', 'velure_hackathon_2026')}"
    f"@{_env('POSTGRES_HOST', 'localhost')}:{_env('POSTGRES_PORT', 5432, int)}/{_env('POSTGRES_DB', 'velure')}",
)
DB_POOL_MIN = _env("DB_POOL_MIN", 2, int)
DB_POOL_MAX = _env("DB_POOL_MAX", 10, int)

# ── Pipeline ────────────────────────────────────────────────────────
DEFAULT_TICK_RATE = _env("TICK_RATE", 0.25, float)
BATCH_SIZE = _env("BATCH_SIZE", 10, int)
FLUSH_INTERVAL_MS = _env("FLUSH_INTERVAL_MS", 500, int)
MAX_STREAM_LEN = _env("MAX_STREAM_LEN", 10000, int)

# ── ML Model Tuning ────────────────────────────────────────────────
IF_CONTAMINATION = _env("IF_CONTAMINATION", 0.05, float)
IF_N_ESTIMATORS = _env("IF_N_ESTIMATORS", 200, int)
LSTM_HIDDEN_DIM = _env("LSTM_HIDDEN_DIM", 64, int)
LSTM_LATENT_DIM = _env("LSTM_LATENT_DIM", 32, int)
LSTM_SEQ_LENGTH = _env("LSTM_SEQ_LENGTH", 60, int)
CISS_WINDOW = _env("CISS_WINDOW", 500, int)
VAR_WINDOW = _env("VAR_WINDOW", 500, int)
VAR_CONFIDENCE = _env("VAR_CONFIDENCE", 0.99, float)

# ── Ensemble Weights ────────────────────────────────────────────────
ENSEMBLE_IF_WEIGHT = _env("ENSEMBLE_IF_WEIGHT", 0.4, float)
ENSEMBLE_LSTM_WEIGHT = _env("ENSEMBLE_LSTM_WEIGHT", 0.4, float)
ENSEMBLE_CISS_WEIGHT = _env("ENSEMBLE_CISS_WEIGHT", 0.2, float)

# ── Alert Thresholds ───────────────────────────────────────────────
ALERT_THRESHOLD_HIGH = _env("ALERT_THRESHOLD_HIGH", 0.7, float)
ALERT_THRESHOLD_CRITICAL = _env("ALERT_THRESHOLD_CRITICAL", 0.85, float)

# ── API / Security ──────────────────────────────────────────────────
CORS_ORIGINS = _env("CORS_ORIGINS", "*")  # Comma-separated for production
API_KEY = _env("VELURE_API_KEY", "")  # Empty = no auth (dev mode)
RATE_LIMIT_PER_MINUTE = _env("RATE_LIMIT_PER_MINUTE", 120, int)

# ── Live Data ───────────────────────────────────────────────────────
FINNHUB_API_KEY = _env("FINNHUB_API_KEY", "")
POLYGON_API_KEY = _env("POLYGON_API_KEY", "")
DATA_MODE = _env("DATA_MODE", "simulator")  # "simulator" | "finnhub" | "hybrid"

# ── Speed Presets ───────────────────────────────────────────────────
SPEED_PRESETS = {
    "slow":   0.50,
    "normal": 0.25,
    "fast":   0.10,
    "turbo":  0.04,
}

# ── Crisis Presets ──────────────────────────────────────────────────
CRISIS_PRESETS = {
    "lehman_2008": {
        "name": "2008 Lehman Collapse",
        "description": "Credit contagion, interbank freeze, equity crash",
        "intensity": 0.95,
        "duration_seconds": 60,
    },
    "covid_2020": {
        "name": "2020 COVID Crash",
        "description": "Liquidity crisis, circuit breakers, VIX spike to 82",
        "intensity": 0.80,
        "duration_seconds": 45,
    },
    "svb_2023": {
        "name": "2023 SVB Bank Run",
        "description": "Regional bank contagion, rate sensitivity shock",
        "intensity": 0.65,
        "duration_seconds": 30,
    },
    "flash_crash": {
        "name": "Flash Crash",
        "description": "HFT-driven liquidity vacuum, 6-minute 1000pt drop",
        "intensity": 0.90,
        "duration_seconds": 20,
    },
    "custom": {
        "name": "Custom Scenario",
        "description": "User-defined crisis parameters",
        "intensity": 0.8,
        "duration_seconds": 30,
    },
}


# ── v3: Model Persistence ──────────────────────────────────────────
MODEL_CHECKPOINT_DIR = _env(
    "MODEL_CHECKPOINT_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "checkpoints"),
)
MODEL_CHECKPOINT_ON_CRISIS = _env("MODEL_CHECKPOINT_ON_CRISIS", 1, int) == 1
MODEL_CHECKPOINT_PERIODIC_SEC = _env("MODEL_CHECKPOINT_PERIODIC_SEC", 300, int)

# ── v3: Watermarking ───────────────────────────────────────────────
WATERMARK_LATENESS_MS = _env("WATERMARK_LATENESS_MS", 300, int)

# ── v3: Copula ─────────────────────────────────────────────────────
ENSEMBLE_COPULA_WEIGHT = _env("ENSEMBLE_COPULA_WEIGHT", 0.10, float)
# After introducing copula, reweight others so total stays 1.0
# Defaults: IF 0.35 / LSTM 0.35 / CISS 0.20 / copula 0.10
if ENSEMBLE_COPULA_WEIGHT > 0:
    ENSEMBLE_IF_WEIGHT = _env("ENSEMBLE_IF_WEIGHT", 0.35, float)
    ENSEMBLE_LSTM_WEIGHT = _env("ENSEMBLE_LSTM_WEIGHT", 0.35, float)
    ENSEMBLE_CISS_WEIGHT = _env("ENSEMBLE_CISS_WEIGHT", 0.20, float)

# ── v3: Alerting ───────────────────────────────────────────────────
ALERT_SLACK_WEBHOOK = _env("ALERT_SLACK_WEBHOOK", "")
ALERT_DISCORD_WEBHOOK = _env("ALERT_DISCORD_WEBHOOK", "")
ALERT_PAGERDUTY_KEY = _env("ALERT_PAGERDUTY_KEY", "")
ALERT_GENERIC_WEBHOOK = _env("ALERT_GENERIC_WEBHOOK", "")
ALERT_EMAIL_SMTP_HOST = _env("ALERT_EMAIL_SMTP_HOST", "")
ALERT_EMAIL_SMTP_PORT = _env("ALERT_EMAIL_SMTP_PORT", 587, int)
ALERT_EMAIL_SMTP_USER = _env("ALERT_EMAIL_SMTP_USER", "")
ALERT_EMAIL_SMTP_PASSWORD = _env("ALERT_EMAIL_SMTP_PASSWORD", "")
ALERT_EMAIL_FROM = _env("ALERT_EMAIL_FROM", "")
ALERT_EMAIL_TO = _env("ALERT_EMAIL_TO", "")
ALERT_DEDUP_WINDOW_SEC = _env("ALERT_DEDUP_WINDOW_SEC", 300, int)
ALERT_MIN_SEVERITY = _env("ALERT_MIN_SEVERITY", "HIGH")  # HIGH|CRITICAL

# ── v3: Replay ─────────────────────────────────────────────────────
REPLAY_DATA_DIR = _env(
    "REPLAY_DATA_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "historical"),
)
REPLAY_SPEED_MULTIPLIER = _env("REPLAY_SPEED_MULTIPLIER", 60.0, float)

# ── v3: TimescaleDB ────────────────────────────────────────────────
USE_TIMESCALE = _env("USE_TIMESCALE", 0, int) == 1
