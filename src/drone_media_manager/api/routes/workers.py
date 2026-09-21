"""Worker pairing and liveness routes."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from collections.abc import Callable
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from drone_media_manager.api.dependencies import require_worker
from drone_media_manager.api.schemas.workers import (
    WorkerHeartbeat,
    WorkerHeartbeatResponse,
    WorkerRegistration,
    WorkerRegistrationResponse,
)
from drone_media_manager.config import ServerSettings
from drone_media_manager.db.models.core import AuditEvent, Worker
from drone_media_manager.domain.enums import WorkerStatus
from drone_media_manager.time import utc_now

bearer = HTTPBearer(auto_error=False)
BearerCredentials = Annotated[
    HTTPAuthorizationCredentials | None, Depends(bearer)
]


def worker_router(
    settings: ServerSettings, session_factory: Callable[[], Session]
) -> APIRouter:
    router = APIRouter(prefix="/api/workers")

    @router.post("/register", status_code=201, response_model=WorkerRegistrationResponse)
    def register(
        request: WorkerRegistration,
        credentials: BearerCredentials,
    ) -> WorkerRegistrationResponse:
        supplied = credentials.credentials if credentials is not None else ""
        expected = settings.worker_bootstrap_token.get_secret_value()
        if credentials is None or credentials.scheme.lower() != "bearer" or not hmac.compare_digest(supplied, expected):
            raise HTTPException(
                status_code=401, detail={"code": "invalid_bootstrap_token"}
            )
        token = secrets.token_hex(32)
        worker = Worker(
            name=request.name,
            token_digest=hashlib.sha256(token.encode()).hexdigest(),
            capabilities_json=json.dumps(request.capabilities, separators=(",", ":")),
            status=WorkerStatus.OFFLINE,
        )
        try:
            with session_factory() as session, session.begin():
                session.add(worker)
                session.flush()
                session.add(
                    AuditEvent(
                        actor="bootstrap",
                        action="worker.register",
                        entity_type="worker",
                        entity_id=worker.id,
                        result="accepted",
                        details_json=json.dumps(
                            {"name": worker.name, "capabilities": request.capabilities},
                            separators=(",", ":"),
                        ),
                        correlation_id=str(uuid4()),
                    )
                )
        except IntegrityError as error:
            raise HTTPException(
                status_code=409, detail={"code": "worker_name_conflict"}
            ) from error
        return WorkerRegistrationResponse(
            worker_id=worker.id,
            worker_token=token,
            status=worker.status,
            revision=worker.revision,
        )

    @router.post("/{worker_id}/heartbeat", response_model=WorkerHeartbeatResponse)
    def heartbeat(
        worker_id: str,
        request: WorkerHeartbeat,
        credentials: BearerCredentials,
    ) -> WorkerHeartbeatResponse:
        del request
        now = utc_now()
        with session_factory() as session, session.begin():
            authenticated = require_worker(session, worker_id, credentials)
            worker = session.get(Worker, authenticated.id)
            assert worker is not None
            if worker.status != WorkerStatus.BUSY:
                worker.status = WorkerStatus.ONLINE
            worker.last_seen_at = now
            worker.revision += 1
            worker.updated_at = now
            session.add(
                AuditEvent(
                    actor=worker.id,
                    action="worker.heartbeat",
                    entity_type="worker",
                    entity_id=worker.id,
                    result="accepted",
                    details_json=json.dumps(
                        {"status": worker.status, "revision": worker.revision},
                        separators=(",", ":"),
                    ),
                    correlation_id=str(uuid4()),
                    occurred_at=now,
                )
            )
        assert worker.last_seen_at is not None
        return WorkerHeartbeatResponse(
            worker_id=worker.id,
            status=worker.status,
            revision=worker.revision,
            last_seen_at=worker.last_seen_at,
        )

    return router
