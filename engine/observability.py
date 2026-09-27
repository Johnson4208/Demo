"""Small, privacy-conscious request logging helpers for SolvAI."""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
from datetime import datetime, timezone


REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
LOGGER = logging.getLogger("solvai.request")


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "event": getattr(record, "event", "application"),
            "message": record.getMessage(),
        }
        for key in ("request_id", "method", "path", "status", "duration_ms"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging():
    if LOGGER.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    LOGGER.addHandler(handler)
    LOGGER.setLevel(os.getenv("SOLVAI_LOG_LEVEL", "INFO").strip().upper() or "INFO")
    LOGGER.propagate = False


def new_request_id(value=None):
    candidate = str(value or "").strip()
    return candidate if REQUEST_ID_RE.fullmatch(candidate) else secrets.token_hex(12)


def log_request(*, request_id, method, path, status, duration_ms):
    level = logging.ERROR if status >= 500 else logging.WARNING if status >= 400 else logging.INFO
    LOGGER.log(
        level,
        "request completed",
        extra={
            "event": "http_request",
            "request_id": request_id,
            "method": method,
            "path": path,
            "status": int(status),
            "duration_ms": round(float(duration_ms), 1),
        },
    )
