"""Observability: request-id propagation, structured JSON logging, request timing."""

from __future__ import annotations

import json
import logging
import time
import uuid
from contextvars import ContextVar

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# ---------------------------------------------------------------------------
# Context variable: request_id available throughout the request lifecycle
# ---------------------------------------------------------------------------
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

logger = logging.getLogger("askhub_ai_server.access")


# ---------------------------------------------------------------------------
# ASGI middleware (streaming-safe, no BaseHTTPMiddleware)
# ---------------------------------------------------------------------------
class ObservabilityMiddleware:
    """Adds request-id header, logs request timing as structured JSON."""

    SKIP_PATHS = frozenset({"/health", "/ready"})

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        rid = request.headers.get("x-request-id") or str(uuid.uuid4())
        request_id_ctx.set(rid)

        # Attach to scope state so downstream handlers can access it
        if "state" not in scope:
            scope["state"] = {}
        scope["state"]["request_id"] = rid

        start = time.monotonic()
        status_code = 0

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = MutableHeaders(scope=message)
                headers.append("x-request-id", rid)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = round((time.monotonic() - start) * 1000)
            if request.url.path not in self.SKIP_PATHS:
                logger.info(
                    "request completed",
                    extra={
                        "request_id": rid,
                        "method": request.method,
                        "path": request.url.path,
                        "status_code": status_code,
                        "duration_ms": duration_ms,
                    },
                )


# ---------------------------------------------------------------------------
# Logging: JSON formatter + request-id filter
# ---------------------------------------------------------------------------
class RequestIdFilter(logging.Filter):
    """Injects request_id from contextvars into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "request_id", None):
            record.request_id = request_id_ctx.get("-")  # type: ignore[attr-defined]
        return True


class JSONFormatter(logging.Formatter):
    """Emits one JSON object per log line for machine consumption."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        # Merge structured extras (e.g. duration_ms, model, etc.)
        for key in ("method", "path", "status_code", "duration_ms", "model", "error"):
            val = getattr(record, key, None)
            if val is not None:
                log_entry[key] = val
        if record.exc_info and record.exc_info[1] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, ensure_ascii=False, default=str)


def configure_logging(log_level: str = "INFO") -> None:
    """Set up root logger with JSON formatter and request-id filter."""
    root = logging.getLogger()
    root.setLevel(log_level.upper())

    # Remove existing handlers to avoid duplicates on reload
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    handler.addFilter(RequestIdFilter())
    root.addHandler(handler)

    # Quiet noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("boto3").setLevel(logging.WARNING)
