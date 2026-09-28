"""Authenticated candidate review and local original-only export jobs."""

from collections.abc import Callable
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from drone_media_manager.api.auth import require_browser_identity, require_csrf
from drone_media_manager.config import ServerSettings
from drone_media_manager.db.models.core import Job
from drone_media_manager.db.models.ingest import Trip
from drone_media_manager.selects.repository import (
    EXPORT_KIND,
    candidates_for_trip,
    enqueue_export,
    export_job,
    generate_candidates,
    review_candidate,
)


class GenerateRequest(BaseModel):
    profile: Literal["instagram", "youtube"] = "instagram"


class ReviewRequest(BaseModel):
    status: Literal["PENDING", "INCLUDE", "REJECT"]
    start_ms: int | None = Field(default=None, ge=-1)
    end_ms: int | None = Field(default=None, ge=-1)


class ExportRequest(BaseModel):
    mode: Literal["FAST", "ACCURATE"] = "FAST"


def selects_router(
    settings: ServerSettings, sessions: Callable[[], Session]
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/editorial/trips/{trip_id}/selects")
    def state(trip_id: str, request: Request) -> dict[str, Any]:
        require_browser_identity(request)
        with sessions() as session:
            if session.get(Trip, trip_id) is None:
                raise HTTPException(404, detail={"code": "trip_not_found"})
            return {"candidates": candidates_for_trip(session, trip_id)}

    @router.post("/api/editorial/trips/{trip_id}/selects")
    def generate(
        trip_id: str, request: Request, payload: GenerateRequest | None = None
    ) -> dict[str, int]:
        require_csrf(request, request.headers.get("x-csrf-token"))
        with sessions() as session, session.begin():
            session.execute(text("BEGIN IMMEDIATE"))
            try:
                count = generate_candidates(
                    session, trip_id, (payload or GenerateRequest()).profile
                )
            except ValueError as error:
                raise HTTPException(404, detail={"code": str(error)}) from error
            return {"candidate_count": count}

    @router.patch("/api/editorial/selects/{candidate_id}")
    def review(
        candidate_id: str, payload: ReviewRequest, request: Request
    ) -> dict[str, object]:
        identity = require_csrf(request, request.headers.get("x-csrf-token"))
        with sessions() as session, session.begin():
            session.execute(text("BEGIN IMMEDIATE"))
            try:
                row = review_candidate(
                    session,
                    candidate_id,
                    payload.status,
                    payload.start_ms,
                    payload.end_ms,
                    identity.user_id,
                )
            except ValueError as error:
                code = 404 if str(error) == "select_candidate_not_found" else 422
                raise HTTPException(code, detail={"code": str(error)}) from error
            return {"id": row.id, "status": row.status}

    @router.post("/api/editorial/trips/{trip_id}/selects/exports", status_code=202)
    def export(
        trip_id: str,
        payload: ExportRequest,
        request: Request,
        background: BackgroundTasks,
    ) -> dict[str, str]:
        require_csrf(request, request.headers.get("x-csrf-token"))
        with sessions() as session:
            try:
                job = enqueue_export(session, trip_id, payload.mode)
            except ValueError as error:
                code = 404 if str(error) == "trip_not_found" else 409
                raise HTTPException(code, detail={"code": str(error)}) from error
            background.add_task(export_job, sessions, settings, job.id)
            return {"id": job.id, "status": job.status}

    @router.get("/api/editorial/select-export-jobs/{job_id}")
    def export_state(job_id: str, request: Request) -> dict[str, Any]:
        require_browser_identity(request)
        with sessions() as session:
            job = session.get(Job, job_id)
            if job is None or job.kind != EXPORT_KIND:
                raise HTTPException(404, detail={"code": "job_not_found"})
            import json

            return {
                **json.loads(job.payload_json),
                "id": job.id,
                "status": job.status,
                "progress": job.progress,
                "error": job.error,
            }

    return router
