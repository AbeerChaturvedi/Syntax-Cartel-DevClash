"""
Project Velure — Security Middleware
Rate limiting, API key validation, and request logging.
"""
import time
from collections import defaultdict
from typing import Optional

from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from utils.logger import api_log as log


class RateLimiter:
    """
    In-memory sliding window rate limiter.
    For production, replace with Redis-backed (e.g., fastapi-limiter).
    """

    def __init__(self, requests_per_minute: int = 120):
        self.rpm = requests_per_minute
        self._windows: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, client_ip: str) -> bool:
        now = time.monotonic()
        window = self._windows[client_ip]

        # Prune old entries (older than 60s)
        self._windows[client_ip] = [t for t in window if now - t < 60]
        window = self._windows[client_ip]

        if len(window) >= self.rpm:
            return False

        window.append(now)
        return True

    def get_remaining(self, client_ip: str) -> int:
        now = time.monotonic()
        window = [t for t in self._windows.get(client_ip, []) if now - t < 60]
        return max(0, self.rpm - len(window))


class SecurityMiddleware(BaseHTTPMiddleware):
    """
    Combined middleware:
    - Rate limiting (per-IP sliding window)
    - Optional API key validation (header: X-API-Key)
    - Request logging with latency tracking
    """

    def __init__(self, app, rate_limit: int = 120, api_key: str = ""):
        super().__init__(app)
        self._limiter = RateLimiter(rate_limit)
        self._api_key = api_key  # Empty string = no auth required

    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        start = time.monotonic()

        # Skip rate limiting for WebSocket upgrades and health checks
        path = request.url.path
        if path in ("/", "/ws/dashboard", "/health"):
            response = await call_next(request)
            return response

        # Rate limiting
        if not self._limiter.is_allowed(client_ip):
            log.warning(f"Rate limited: {client_ip} on {path}")
            return JSONResponse(
                status_code=429,
                content={"error": "rate_limited", "message": "Too many requests. Try again in 60s."},
                headers={"Retry-After": "60"},
            )

        # API key validation (if configured)
        if self._api_key:
            provided_key = request.headers.get("X-API-Key", "")
            if provided_key != self._api_key:
                log.warning(f"Unauthorized request from {client_ip} to {path}")
                return JSONResponse(
                    status_code=401,
                    content={"error": "unauthorized", "message": "Invalid or missing API key."},
                )

        # Process request
        response = await call_next(request)

        # Log request
        elapsed_ms = (time.monotonic() - start) * 1000
        log.info(
            f"{request.method} {path} → {response.status_code} ({elapsed_ms:.1f}ms)",
            extra={"latency_ms": round(elapsed_ms, 1)},
        )

        # Add rate limit headers
        remaining = self._limiter.get_remaining(client_ip)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Limit"] = str(self._limiter.rpm)

        return response
