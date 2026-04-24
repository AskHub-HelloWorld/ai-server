"""Lightweight circuit breaker for external service calls (LLM, etc.).

States
------
CLOSED   → Normal operation. Failures are counted.
OPEN     → Consecutive failures exceeded threshold. All calls are rejected
           immediately for ``recovery_timeout`` seconds.
HALF_OPEN → After recovery timeout, ONE probe call is allowed through.
            Success → CLOSED.  Failure → back to OPEN.
"""

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from enum import Enum

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Thread-safe circuit breaker with in-memory state."""

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        name: str = "default",
    ) -> None:
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._name = name

        self._lock = threading.Lock()
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._last_failure_time: float = 0.0

        # Cumulative metrics (monotonic counters)
        self._total_calls = 0
        self._total_successes = 0
        self._total_failures = 0
        self._total_rejections = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def state(self) -> CircuitState:
        with self._lock:
            return self._effective_state()

    def allow_request(self) -> bool:
        """Return True if a call is allowed, False if circuit is OPEN."""
        with self._lock:
            effective = self._effective_state()
            if effective == CircuitState.OPEN:
                self._total_rejections += 1
                return False
            # CLOSED or HALF_OPEN → allow
            return True

    def record_success(self) -> None:
        with self._lock:
            self._total_calls += 1
            self._total_successes += 1
            if self._state != CircuitState.CLOSED:
                logger.info(
                    "circuit breaker %s: recovered → CLOSED",
                    self._name,
                    extra={"circuit": self._name},
                )
            self._state = CircuitState.CLOSED
            self._consecutive_failures = 0

    def record_failure(self) -> None:
        with self._lock:
            self._total_calls += 1
            self._total_failures += 1
            self._consecutive_failures += 1
            self._last_failure_time = time.monotonic()
            if self._consecutive_failures >= self._failure_threshold:
                if self._state != CircuitState.OPEN:
                    logger.warning(
                        "circuit breaker %s: OPEN after %d consecutive failures",
                        self._name,
                        self._consecutive_failures,
                        extra={
                            "circuit": self._name,
                            "consecutive_failures": self._consecutive_failures,
                        },
                    )
                self._state = CircuitState.OPEN

    @property
    def metrics(self) -> dict:
        with self._lock:
            return {
                "name": self._name,
                "state": self._effective_state().value,
                "consecutive_failures": self._consecutive_failures,
                "total_calls": self._total_calls,
                "total_successes": self._total_successes,
                "total_failures": self._total_failures,
                "total_rejections": self._total_rejections,
            }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _effective_state(self) -> CircuitState:
        """Derive current state, promoting OPEN → HALF_OPEN when recovery timeout expires.

        Must be called under ``self._lock``.
        """
        if self._state == CircuitState.OPEN:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self._recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                logger.info(
                    "circuit breaker %s: HALF_OPEN — allowing probe request",
                    self._name,
                    extra={"circuit": self._name},
                )
        return self._state


@contextmanager
def circuit_protected(circuit: CircuitBreaker, operation: str, model: str):
    """서킷 브레이커 체크 + 타이밍 + 성공/실패 기록을 감싸는 컨텍스트 매니저.

    사용 예::

        with circuit_protected(self._circuit, "converse", self._model_id):
            response = self._client.converse(...)
            return _extract_text_response(response)
    """
    from askhub_ai_server.services.exceptions import LLMCircuitOpenError

    if not circuit.allow_request():
        raise LLMCircuitOpenError()

    start = time.monotonic()
    try:
        yield
    except LLMCircuitOpenError:
        raise
    except Exception:
        duration_ms = round((time.monotonic() - start) * 1000)
        circuit.record_failure()
        logger.error(
            "LLM %s failed",
            operation,
            extra={"model": model, "duration_ms": duration_ms},
            exc_info=True,
        )
        raise
    else:
        duration_ms = round((time.monotonic() - start) * 1000)
        circuit.record_success()
        logger.info(
            "LLM %s completed",
            operation,
            extra={"model": model, "duration_ms": duration_ms},
        )
