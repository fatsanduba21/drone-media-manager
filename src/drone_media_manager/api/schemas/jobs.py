"""Strict schemas for leased job mutations."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from drone_media_manager.api.schemas.workers import StrictSchema


class ClaimRequest(StrictSchema):
    worker_id: str = Field(min_length=1, max_length=36)
    idempotency_key: UUID
    lease_seconds: int = Field(default=60, ge=5, le=3600)


class ClaimResponse(StrictSchema):
    job_id: str
    kind: str
    payload: dict[str, Any]
    status: str
    revision: int
    attempts: int
    progress: float
    lease_expires_at: datetime
    lease_token: str


class LeaseMutation(StrictSchema):
    worker_id: str = Field(min_length=1, max_length=36)
    lease_token: str = Field(min_length=1, max_length=256)
    revision: int = Field(ge=0)
    idempotency_key: UUID


class ProgressRequest(LeaseMutation):
    progress: float = Field(ge=0, le=1, allow_inf_nan=False)


class CompleteRequest(LeaseMutation):
    pass


class FailRequest(LeaseMutation):
    error: str = Field(min_length=1, max_length=512)


class JobMutationResponse(StrictSchema):
    job_id: str
    status: str
    revision: int
    progress: float
