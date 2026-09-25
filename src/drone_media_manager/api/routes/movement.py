"""Authenticated local movement analysis and human review."""

from __future__ import annotations

import json
from collections.abc import Callable
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from drone_media_manager.api.auth import require_browser_identity, require_csrf
from drone_media_manager.config import ServerSettings
from drone_media_manager.db.models.catalog import CatalogAsset
from drone_media_manager.db.models.core import AuditEvent, Job
from drone_media_manager.movement.classifier import MOVEMENTS
from drone_media_manager.movement.models import MovementAnalysis, MovementReview
from drone_media_manager.movement.repository import (
    JOB_KIND,
    enqueue_job,
    review_movement,
    run_job,
)


class MovementRequest(BaseModel):
    value: str = Field(min_length=1, max_length=64)
    start_ms: int = Field(default=-1, ge=-1)
    end_ms: int = Field(default=-1, ge=-1)


class ReferenceRequest(BaseModel):
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)


def movement_router(
    settings: ServerSettings, sessions: Callable[[], Session]
) -> APIRouter:
    router = APIRouter()

    @router.post("/api/editorial/trips/{trip_id}/movements", status_code=202)
    def analyze(
        trip_id: str, request: Request, background: BackgroundTasks
    ) -> dict[str, str]:
        require_csrf(request, request.headers.get("x-csrf-token"))
        with sessions() as session:
            try:
                job = enqueue_job(session, trip_id)
            except ValueError as error:
                raise HTTPException(404, detail={"code": str(error)}) from error
            background.add_task(run_job, sessions, settings, job.id)
            return {"id": job.id, "status": job.status}

    @router.get("/api/editorial/movement-jobs/{job_id}")
    def job_state(job_id: str, request: Request) -> dict[str, object]:
        require_browser_identity(request)
        with sessions() as session:
            job = session.get(Job, job_id)
            if job is None or job.kind != JOB_KIND:
                raise HTTPException(404, detail={"code": "job_not_found"})
            return {
                "id": job.id,
                "status": job.status,
                "progress": job.progress,
                "error": job.error,
                **json.loads(job.payload_json),
            }

    @router.get("/api/editorial/assets/{asset_id}/movement")
    def state(asset_id: str, request: Request) -> dict[str, object]:
        require_browser_identity(request)
        with sessions() as session:
            asset = session.get(CatalogAsset, asset_id)
            if asset is None:
                raise HTTPException(404, detail={"code": "asset_not_found"})
            analysis = session.scalar(
                select(MovementAnalysis).where(
                    MovementAnalysis.catalog_asset_id == asset_id,
                    MovementAnalysis.superseded_at.is_(None),
                )
            )
            reviews = list(
                session.scalars(
                    select(MovementReview)
                    .where(MovementReview.catalog_asset_id == asset_id)
                    .order_by(MovementReview.start_ms)
                )
            )
            whole = next((r for r in reviews if r.start_ms == -1), None)
            return {
                "asset_id": asset.id,
                "duration_ms": asset.duration_ms,
                "classes": MOVEMENTS,
                "final": asset.movement,
                "source": "HUMAN"
                if whole and whole.value is not None
                else "IMPORTED"
                if asset.movement
                else None,
                "locked": bool(whole and whole.value is not None),
                "reference": {
                    "latitude": whole.anchor_lat,
                    "longitude": whole.anchor_lon,
                }
                if whole and whole.anchor_lat is not None
                else None,
                "suggestion": {
                    "id": analysis.id,
                    "value": analysis.value,
                    "confidence": analysis.confidence,
                    "algorithm_version": analysis.algorithm_version,
                    "evidence": json.loads(analysis.evidence_json),
                }
                if analysis
                else None,
                "segments": json.loads(analysis.segments_json) if analysis else [],
                "confirmed_segments": [
                    {
                        "id": r.id,
                        "start_ms": r.start_ms,
                        "end_ms": r.end_ms,
                        "value": r.value,
                        "source": r.source,
                        "locked": r.locked,
                    }
                    for r in reviews
                    if r.start_ms >= 0
                ],
            }

    @router.patch("/api/editorial/assets/{asset_id}/movement")
    def confirm(
        asset_id: str, payload: MovementRequest, request: Request
    ) -> dict[str, str]:
        identity = require_csrf(request, request.headers.get("x-csrf-token"))
        with sessions() as session, session.begin():
            session.execute(text("BEGIN IMMEDIATE"))
            try:
                row = review_movement(
                    session,
                    asset_id,
                    payload.value,
                    actor=identity.user_id,
                    start_ms=payload.start_ms,
                    end_ms=payload.end_ms,
                )
            except ValueError as error:
                raise HTTPException(422, detail={"code": str(error)}) from error
            return {"id": row.id}

    @router.put("/api/editorial/assets/{asset_id}/movement/reference")
    def reference(
        asset_id: str, payload: ReferenceRequest, request: Request
    ) -> dict[str, str]:
        identity = require_csrf(request, request.headers.get("x-csrf-token"))
        with sessions() as session, session.begin():
            session.execute(text("BEGIN IMMEDIATE"))
            try:
                row = review_movement(
                    session,
                    asset_id,
                    None,
                    actor=identity.user_id,
                    anchor=(payload.latitude, payload.longitude),
                )
            except ValueError as error:
                raise HTTPException(422, detail={"code": str(error)}) from error
            return {"id": row.id}

    @router.delete("/api/editorial/assets/{asset_id}/movement/segments/{review_id}")
    def remove_segment(
        asset_id: str, review_id: str, request: Request
    ) -> dict[str, bool]:
        identity = require_csrf(request, request.headers.get("x-csrf-token"))
        with sessions() as session, session.begin():
            row = session.get(MovementReview, review_id)
            if row is None or row.catalog_asset_id != asset_id or row.start_ms < 0:
                raise HTTPException(404, detail={"code": "segment_not_found"})
            session.add(
                AuditEvent(
                    actor=identity.user_id,
                    action="movement.segment.remove",
                    entity_type="catalog_asset",
                    entity_id=asset_id,
                    result="accepted",
                    details_json=json.dumps(
                        {
                            "value": row.value,
                            "start_ms": row.start_ms,
                            "end_ms": row.end_ms,
                        }
                    ),
                    correlation_id=str(uuid4()),
                )
            )
            session.delete(row)
            return {"removed": True}

    return router
