"""
Project Velure — Structured Logging
JSON-formatted logs for production observability.
"""
import logging
import json
import sys
import time
from datetime import datetime, timezone


class VelureJSONFormatter(logging.Formatter):
    """JSON log formatter for structured log aggregation (ELK, CloudWatch, etc.)."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)
        # Merge extra fields
        for key in ("component", "tick_id", "latency_ms", "model", "asset", "error_type", "client_count"):
            val = getattr(record, key, None)
            if val is not None:
                log_entry[key] = val
        return json.dumps(log_entry, default=str)


def get_logger(name: str) -> logging.Logger:
    """Get a named logger with structured JSON output."""
    logger = logging.getLogger(f"velure.{name}")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(VelureJSONFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


# Pre-built loggers for each subsystem
pipeline_log = get_logger("pipeline")
model_log = get_logger("model")
ws_log = get_logger("websocket")
db_log = get_logger("database")
redis_log = get_logger("redis")
api_log = get_logger("api")
ingestion_log = get_logger("ingestion")
