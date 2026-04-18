"""
Project Velure — Circuit Breaker
Prevents cascading failures when downstream services (Redis, PostgreSQL) are unhealthy.
"""
import time
import asyncio
from enum import Enum
from utils.logger import get_logger

log = get_logger("circuit_breaker")


class CircuitState(Enum):
    CLOSED = "closed"          # Healthy — requests flow through
    OPEN = "open"              # Tripped — requests fail fast
    HALF_OPEN = "half_open"    # Testing — one request allowed through


class CircuitBreaker:
    """
    Async-compatible circuit breaker.
    
    - CLOSED: Normal operation. Tracks failures.
    - OPEN: After `failure_threshold` consecutive failures, trips open.
             All calls fail fast for `recovery_timeout` seconds.
    - HALF_OPEN: After recovery_timeout, allows one probe request.
                 If it succeeds → CLOSED. If it fails → OPEN again.
    """

    def __init__(self, name: str, failure_threshold: int = 5, recovery_timeout: float = 30.0):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._success_count = 0
        self._total_trips = 0

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if time.monotonic() - self._last_failure_time >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                log.info(f"Circuit '{self.name}' → HALF_OPEN (probing)")
        return self._state

    @property
    def is_available(self) -> bool:
        return self.state != CircuitState.OPEN

    def record_success(self):
        if self._state == CircuitState.HALF_OPEN:
            log.info(f"Circuit '{self.name}' → CLOSED (recovered)")
            self._total_trips += 0  # Keep count
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count += 1

    def record_failure(self):
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._failure_count >= self.failure_threshold:
            if self._state != CircuitState.OPEN:
                self._total_trips += 1
                log.warning(
                    f"Circuit '{self.name}' → OPEN (tripped after {self._failure_count} failures, "
                    f"will retry in {self.recovery_timeout}s)"
                )
            self._state = CircuitState.OPEN

    def get_status(self) -> dict:
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "total_trips": self._total_trips,
        }


# Pre-built circuit breakers for each dependency
redis_circuit = CircuitBreaker("redis", failure_threshold=5, recovery_timeout=15.0)
db_circuit = CircuitBreaker("postgresql", failure_threshold=3, recovery_timeout=30.0)
