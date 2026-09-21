"""RED tests for structured audit logging and secret redaction."""

from __future__ import annotations

import json
import logging

from drone_media_manager.logging import JsonLogFormatter


def test_json_log_redacts_tokens_and_detailed_gps_tracks() -> None:
    record = logging.LogRecord(
        name="dmm",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="job recovered",
        args=(),
        exc_info=None,
    )
    record.event = "job_recovered"
    record.correlation_id = "corr-1"
    record.actor = "system"
    record.entity = "job-1"
    record.result = "success"
    record.authorization = "Bearer secret-token"
    record.worker_token = "permanent-secret"
    record.gps_track = [{"lat": -23.55, "lon": -46.63}]

    payload = json.loads(JsonLogFormatter().format(record))

    assert "secret-token" not in json.dumps(payload)
    assert "permanent-secret" not in json.dumps(payload)
    assert payload["authorization"] == "[REDACTED]"
    assert payload["gps_track"] == "[REDACTED]"
    assert {
        "timestamp",
        "level",
        "event",
        "correlation_id",
        "actor",
        "entity",
        "result",
    } <= payload.keys()
