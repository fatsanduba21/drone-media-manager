"""Structured JSON logging with conservative secret redaction."""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

_REDACTED = "[REDACTED]"
_SENSITIVE_PARTS = (
    "token",
    "secret",
    "credential",
    "password",
    "authorization",
    "api_key",
    "private_key",
)
_GPS_PARTS = ("gps", "latitude", "longitude", "lat", "lon", "track", "telemetry")
_CONFIGURED = False
_STANDARD_RECORD_FIELDS = set(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__
)


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in _SENSITIVE_PARTS) or any(
        part in normalized for part in _GPS_PARTS
    )


def _redact(value: Any, key: str | None = None) -> Any:
    if key is not None and _is_sensitive_key(key):
        return _REDACTED
    if isinstance(value, dict):
        return {str(k): _redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "event": getattr(record, "event", record.getMessage()),
            "correlation_id": getattr(record, "correlation_id", None),
            "actor": getattr(record, "actor", None),
            "entity": getattr(record, "entity", None),
            "result": getattr(record, "result", None),
        }
        message = record.getMessage()
        if message:
            payload["message"] = _redact(message)
        for key, value in record.__dict__.items():
            if key in _STANDARD_RECORD_FIELDS or key in payload or key.startswith("_"):
                continue
            payload[key] = _redact(value, key)
        return json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"), default=str
        )


def configure_logging(log_path: Path | None = None) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    selected_path = log_path or (
        Path(os.environ["DMM_LOG_PATH"]) if os.environ.get("DMM_LOG_PATH") else None
    )
    if selected_path is not None:
        selected_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(
            RotatingFileHandler(
                selected_path,
                maxBytes=10 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            )
        )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    formatter = JsonLogFormatter()
    for handler in handlers:
        handler.setFormatter(formatter)
        root.addHandler(handler)
    _CONFIGURED = True
