"""Strict localhost-admin ingest confirmation schemas."""

from __future__ import annotations

from pydantic import Field

from drone_media_manager.api.schemas.workers import StrictSchema


class IngestConfirmationRequest(StrictSchema):
    snapshot_id: str = Field(min_length=1, max_length=36)
    trip_id: str = Field(min_length=1, max_length=36)
    revision: int = Field(ge=0)


class IngestResponse(StrictSchema):
    ingest_id: str
    status: str
    revision: int
    trip_id: str
    snapshot_id: str | None
