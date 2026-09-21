"""Authenticated pull and fenced mutation routes for worker jobs."""

from __future__ import annotations

import json
import re
from collections.abc import Callable

from fastapi import APIRouter, HTTPException, Response
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from drone_media_manager.api.dependencies import require_worker
from drone_media_manager.api.routes.workers import BearerCredentials
from drone_media_manager.api.schemas.jobs import (
    ClaimRequest,
    ClaimResponse,
    CompleteRequest,
    FailRequest,
    JobMutationResponse,
    LeaseMutation,
    ProgressRequest,
)
from drone_media_manager.db.models.core import AuditEvent, Job, Worker
from drone_media_manager.domain.enums import WorkerStatus
from drone_media_manager.domain.errors import InvalidTransition, LeaseConflict
from drone_media_manager.jobs.repository import ClaimedJob, JobRepository
from drone_media_manager.time import utc_now


def _audit_hook(
    *, worker_id: str, action: str, correlation_id: str
) -> Callable[[Session, Job], None]:
    def write_audit(session: Session, job: Job) -> None:
        if action in {"job.claim", "job.complete", "job.fail"}:
            worker = session.get(Worker, worker_id)
            if worker is not None:
                worker.status = (
                    WorkerStatus.BUSY
                    if action == "job.claim"
                    else WorkerStatus.ONLINE
                )
                worker.updated_at = utc_now()
        session.add(
            AuditEvent(
                actor=worker_id,
                action=action,
                entity_type="job",
                entity_id=job.id,
                result="accepted",
                details_json=json.dumps(
                    {
                        "status": job.status,
                        "revision": job.revision,
                        "progress": job.progress,
                    },
                    separators=(",", ":"),
                ),
                correlation_id=correlation_id,
            )
        )

    return write_audit


def _authenticate(
    session_factory: Callable[[], Session],
    worker_id: str,
    credentials: HTTPAuthorizationCredentials | None,
) -> frozenset[str]:
    with session_factory() as session:
        authenticated = require_worker(session, worker_id, credentials)
        return authenticated.capabilities


def _sanitize_error(value: str) -> str:
    sanitized = re.sub(r"(?i)bearer\s+\S+", "Bearer [REDACTED]", value)
    sanitized = re.sub(r"(?i)token\s*=\s*\S+", "token=[REDACTED]", sanitized)
    sanitized = " ".join(sanitized.split())
    return sanitized[:512]


def _mutation_response(job: ClaimedJob) -> JobMutationResponse:
    return JobMutationResponse(
        job_id=job.id,
        status=job.status,
        revision=job.revision,
        progress=job.progress,
    )


def job_router(session_factory: Callable[[], Session]) -> APIRouter:
    router = APIRouter(prefix="/api/worker-jobs")

    @router.post("/claim", response_model=ClaimResponse)
    def claim(
        request: ClaimRequest,
        credentials: BearerCredentials,
    ) -> ClaimResponse | Response:
        capabilities = _authenticate(session_factory, request.worker_id, credentials)
        with session_factory() as session:
            repository = JobRepository(
                session,
                on_mutation=_audit_hook(
                    worker_id=request.worker_id,
                    action="job.claim",
                    correlation_id=str(request.idempotency_key),
                ),
            )
            try:
                job = repository.claim(request.worker_id, capabilities, request.lease_seconds)
            except LeaseConflict as error:
                raise HTTPException(status_code=409, detail={"code": "invalid_lease"}) from error
        if job is None:
            return Response(status_code=204)
        assert job.lease_token is not None and job.lease_expires_at is not None
        payload = json.loads(job.payload_json)
        if not isinstance(payload, dict):
            raise HTTPException(status_code=500, detail={"code": "invalid_job_payload"})
        return ClaimResponse(
            job_id=job.id,
            kind=job.kind,
            payload=payload,
            status=job.status,
            revision=job.revision,
            attempts=job.attempts,
            progress=job.progress,
            lease_expires_at=job.lease_expires_at,
            lease_token=job.lease_token,
        )

    def mutate(
        job_id: str,
        request: LeaseMutation,
        credentials: HTTPAuthorizationCredentials | None,
        action: str,
    ) -> JobMutationResponse:
        _authenticate(session_factory, request.worker_id, credentials)
        with session_factory() as session:
            repository = JobRepository(
                session,
                on_mutation=_audit_hook(
                    worker_id=request.worker_id,
                    action=action,
                    correlation_id=str(request.idempotency_key),
                ),
            )
            try:
                if isinstance(request, ProgressRequest):
                    job = repository.progress(
                        job_id,
                        request.worker_id,
                        request.lease_token,
                        request.revision,
                        request.progress,
                    )
                elif isinstance(request, FailRequest):
                    job = repository.fail(
                        job_id,
                        request.worker_id,
                        request.lease_token,
                        request.revision,
                        _sanitize_error(request.error),
                    )
                else:
                    job = repository.complete(
                        job_id,
                        request.worker_id,
                        request.lease_token,
                        request.revision,
                    )
            except InvalidTransition as error:
                raise HTTPException(
                    status_code=409, detail={"code": "invalid_transition"}
                ) from error
            except LeaseConflict as error:
                raise HTTPException(
                    status_code=409, detail={"code": error.reason.value}
                ) from error
        return _mutation_response(job)

    @router.post("/{job_id}/progress", response_model=JobMutationResponse)
    def progress(
        job_id: str,
        request: ProgressRequest,
        credentials: BearerCredentials,
    ) -> JobMutationResponse:
        return mutate(job_id, request, credentials, "job.progress")

    @router.post("/{job_id}/complete", response_model=JobMutationResponse)
    def complete(
        job_id: str,
        request: CompleteRequest,
        credentials: BearerCredentials,
    ) -> JobMutationResponse:
        return mutate(job_id, request, credentials, "job.complete")

    @router.post("/{job_id}/fail", response_model=JobMutationResponse)
    def fail(
        job_id: str,
        request: FailRequest,
        credentials: BearerCredentials,
    ) -> JobMutationResponse:
        return mutate(job_id, request, credentials, "job.fail")

    return router
