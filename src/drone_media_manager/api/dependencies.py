"""Authentication helpers shared by worker-facing routes."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass

from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.orm import Session

from drone_media_manager.db.models.core import Worker


@dataclass(frozen=True)
class AuthenticatedWorker:
    id: str
    capabilities: frozenset[str]


def require_worker(
    session: Session,
    worker_id: str,
    credentials: HTTPAuthorizationCredentials | None,
) -> AuthenticatedWorker:
    """Authenticate the exact worker named by the request without exposing tokens."""
    supplied = credentials.credentials if credentials is not None else ""
    supplied_digest = hashlib.sha256(supplied.encode()).hexdigest()
    worker = session.get(Worker, worker_id)
    stored_digest = worker.token_digest if worker is not None else "0" * 64
    digest_matches = hmac.compare_digest(stored_digest, supplied_digest)
    valid = (
        credentials is not None
        and credentials.scheme.lower() == "bearer"
        and worker is not None
        and digest_matches
    )
    if not valid:
        raise HTTPException(status_code=401, detail={"code": "invalid_worker_token"})
    assert worker is not None
    capabilities = json.loads(worker.capabilities_json)
    if not isinstance(capabilities, list) or not all(
        isinstance(item, str) for item in capabilities
    ):
        raise HTTPException(
            status_code=500, detail={"code": "invalid_worker_capabilities"}
        )
    return AuthenticatedWorker(worker.id, frozenset(capabilities))


def require_authenticated_worker(
    session: Session, credentials: HTTPAuthorizationCredentials | None
) -> AuthenticatedWorker:
    """Authenticate a worker token when the requested target is not yet trusted."""

    supplied = credentials.credentials if credentials is not None else ""
    supplied_digest = hashlib.sha256(supplied.encode()).hexdigest()
    worker = next(
        (
            candidate
            for candidate in session.scalars(select(Worker))
            if hmac.compare_digest(candidate.token_digest, supplied_digest)
        ),
        None,
    )
    if credentials is None or credentials.scheme.lower() != "bearer" or worker is None:
        raise HTTPException(status_code=401, detail={"code": "invalid_worker_token"})
    capabilities = json.loads(worker.capabilities_json)
    if not isinstance(capabilities, list) or not all(
        isinstance(item, str) for item in capabilities
    ):
        raise HTTPException(
            status_code=500, detail={"code": "invalid_worker_capabilities"}
        )
    return AuthenticatedWorker(worker.id, frozenset(capabilities))
