"""Authenticated score profiles, local jobs and explainable rankings."""

from collections.abc import Callable
from typing import Annotated, Any, Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from drone_media_manager.api.auth import require_browser_identity, require_csrf
from drone_media_manager.config import ServerSettings
from drone_media_manager.db.models.core import Job
from drone_media_manager.db.models.ingest import Trip
from drone_media_manager.scoring.repository import (
    JOB_KIND,
    enqueue_job,
    job_data,
    profile_weights,
    run_job,
    save_profile,
)
from drone_media_manager.scoring.service import DEFAULT_PROFILES

ProfileName = Literal["instagram", "youtube"]


class ScoreRequest(BaseModel):
    profile: ProfileName = "instagram"


class WeightsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    weights: dict[str, Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)]] = (
        Field(min_length=1, max_length=6)
    )


def scoring_router(
    settings: ServerSettings, sessions: Callable[[], Session]
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/editorial/score-profiles")
    def profiles(request: Request) -> dict[str, dict[str, float]]:
        require_browser_identity(request)
        with sessions() as session:
            return {name: profile_weights(session, name) for name in DEFAULT_PROFILES}

    @router.put("/api/editorial/score-profiles/{profile}")
    def update_profile(
        profile: ProfileName, payload: WeightsRequest, request: Request
    ) -> dict[str, float]:
        identity = require_csrf(request, request.headers.get("x-csrf-token"))
        with sessions() as session, session.begin():
            try:
                return save_profile(session, profile, payload.weights, identity.user_id)
            except ValueError as error:
                raise HTTPException(422, detail={"code": str(error)}) from error

    @router.post("/api/editorial/trips/{trip_id}/scores", status_code=202)
    def analyze(
        trip_id: str,
        payload: ScoreRequest,
        request: Request,
        background: BackgroundTasks,
    ) -> dict[str, str]:
        require_csrf(request, request.headers.get("x-csrf-token"))
        with sessions() as session:
            try:
                job = enqueue_job(session, trip_id, payload.profile)
            except ValueError as error:
                raise HTTPException(404, detail={"code": str(error)}) from error
            background.add_task(run_job, sessions, settings, job.id)
            return {"id": job.id, "status": job.status}

    @router.get("/api/editorial/score-jobs/{job_id}")
    def job_state(job_id: str, request: Request) -> dict[str, Any]:
        require_browser_identity(request)
        with sessions() as session:
            job = session.get(Job, job_id)
            if job is None or job.kind != JOB_KIND:
                raise HTTPException(404, detail={"code": "job_not_found"})
            return job_data(session, job)

    @router.get("/api/editorial/trips/{trip_id}/scores")
    def ranking(
        trip_id: str, request: Request, profile: ProfileName = "instagram"
    ) -> dict[str, Any]:
        require_browser_identity(request)
        with sessions() as session:
            if session.get(Trip, trip_id) is None:
                raise HTTPException(404, detail={"code": "trip_not_found"})
            job = session.scalar(
                select(Job)
                .where(
                    Job.kind == JOB_KIND,
                    func.json_extract(Job.payload_json, "$.trip_id") == trip_id,
                    func.json_extract(Job.payload_json, "$.profile") == profile,
                )
                .order_by(Job.created_at.desc(), Job.id.desc())
                .limit(1)
            )
            return (
                job_data(session, job)
                if job
                else {"status": "NOT_ANALYZED", "results": [], "stale": False}
            )

    return router
