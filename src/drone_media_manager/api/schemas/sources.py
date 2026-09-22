"""Strict wire schemas for worker-uploaded source snapshots."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, field_validator

from drone_media_manager.api.schemas.workers import StrictSchema
from drone_media_manager.domain.enums import PairStatus, SourceKind


class SnapshotCreateRequest(StrictSchema):
    worker_id: str = Field(min_length=1, max_length=36)
    source_kind: SourceKind
    source_volume_identity: str | None = Field(default=None, max_length=1024)
    expires_at: datetime


class SnapshotEntryRequest(StrictSchema):
    source_rel_path: str = Field(min_length=1, max_length=1024)
    size_bytes: int = Field(ge=0)
    mtime_ns: int = Field(ge=0)
    file_identity: str = Field(min_length=1, max_length=1024)
    pair_status: PairStatus | None = None

    @field_validator("source_rel_path")
    @classmethod
    def source_path_is_relative(cls, value: str) -> str:
        if "\\" in value or value.startswith(("/", "\\")) or ":" in value:
            raise ValueError("source_rel_path must be a relative logical path")
        parts = value.replace("\\", "/").split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise ValueError("source_rel_path must not escape its source root")
        return "/".join(parts)


class SnapshotEntriesRequest(StrictSchema):
    worker_id: str = Field(min_length=1, max_length=36)
    revision: int = Field(ge=0)
    entries: list[SnapshotEntryRequest] = Field(min_length=1, max_length=500)


class SnapshotFinalizeRequest(StrictSchema):
    worker_id: str = Field(min_length=1, max_length=36)
    revision: int = Field(ge=0)
    declared_item_count: int = Field(ge=0)


class SnapshotResponse(StrictSchema):
    snapshot_id: str
    status: str
    revision: int
    declared_item_count: int | None = None
    source_fingerprint: str | None = None
