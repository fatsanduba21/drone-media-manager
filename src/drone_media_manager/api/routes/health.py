"""Read-only health reporting for the control plane."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from drone_media_manager.config import ServerSettings
from drone_media_manager.db.models.core import Worker
from drone_media_manager.system.dependencies import DependencyStatus, probe_executable


def health_router(settings: ServerSettings, session_factory: Callable[[], Session], probe: Callable[[str], DependencyStatus] = probe_executable) -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    def health() -> dict[str, Any]:
        components: dict[str, Any] = {
            "database": _database_status(session_factory),
            "omv": _omv_status(settings.omv_root),
            "ffmpeg": _dependency_payload(probe("ffmpeg")),
            "ffprobe": _dependency_payload(probe("ffprobe")),
            "worker_summary": _worker_summary(session_factory),
        }
        overall = "healthy" if all(_is_healthy(value) for value in components.values()) else "degraded"
        return {"status": overall, "components": components}

    return router


def _database_status(session_factory: Callable[[], Session]) -> dict[str, str]:
    try:
        with session_factory() as session:
            session.execute(text("SELECT 1"))
        return {"state": "healthy"}
    except SQLAlchemyError as error:  # pragma: no cover
        return {"state": "degraded", "detail": type(error).__name__}


def _omv_status(root: Any) -> dict[str, str]:
    try:
        readable = root.is_dir() and os.access(root, os.R_OK)
        return {"state": "healthy" if readable else "degraded"}
    except OSError as error:  # pragma: no cover
        return {"state": "degraded", "detail": type(error).__name__}


def _worker_summary(session_factory: Callable[[], Session]) -> dict[str, Any]:
    try:
        with session_factory() as session:
            rows = session.query(Worker.status).all()
        counts: dict[str, int] = {}
        for (status,) in rows:
            counts[str(status)] = counts.get(str(status), 0) + 1
        return {"state": "healthy", "counts": counts, "total": len(rows)}
    except SQLAlchemyError as error:  # pragma: no cover
        return {"state": "degraded", "detail": type(error).__name__}


def _dependency_payload(status: DependencyStatus) -> dict[str, Any]:
    return {"state": status.state, "detail": status.detail, "returncode": status.returncode}


def _is_healthy(value: Any) -> bool:
    return isinstance(value, dict) and value.get("state") == "healthy"
