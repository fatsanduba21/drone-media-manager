"""Worker-authenticated draft, entry, and finalization source snapshot routes."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.orm import Session

from drone_media_manager.api.dependencies import require_authenticated_worker
from drone_media_manager.api.routes.workers import BearerCredentials
from drone_media_manager.api.schemas.sources import (
    SnapshotCreateRequest,
    SnapshotEntriesRequest,
    SnapshotEntryRequest,
    SnapshotFinalizeRequest,
    SnapshotResponse,
)
from drone_media_manager.db.models.ingest import SourceSnapshot, SourceSnapshotEntry
from drone_media_manager.domain.errors import StaleRevision


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _response(snapshot: SourceSnapshot) -> SnapshotResponse:
    return SnapshotResponse(
        snapshot_id=snapshot.id,
        status=snapshot.status,
        revision=snapshot.revision,
        declared_item_count=snapshot.declared_item_count,
        source_fingerprint=snapshot.source_fingerprint,
    )


def _fingerprint(
    snapshot: SourceSnapshot, entries: Sequence[SourceSnapshotEntry]
) -> str:
    payload = {
        "source_kind": snapshot.source_kind,
        "volume_identity": snapshot.source_volume_identity,
        "entries": [
            {
                "relative_path": entry.source_rel_path,
                "size": entry.size_bytes,
                "mtime_ns": entry.mtime_ns,
            }
            for entry in sorted(entries, key=lambda item: item.source_rel_path)
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _owned_snapshot(
    session: Session,
    snapshot_id: str,
    worker_id: str,
    credentials: HTTPAuthorizationCredentials | None,
) -> SourceSnapshot:
    authenticated = require_authenticated_worker(session, credentials)
    snapshot = session.get(SourceSnapshot, snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail={"code": "snapshot_not_found"})
    if authenticated.id != snapshot.worker_id:
        raise HTTPException(
            status_code=403, detail={"code": "snapshot_worker_mismatch"}
        )
    return snapshot


def _draft(snapshot: SourceSnapshot, expected_revision: int) -> None:
    if snapshot.status != "DRAFT":
        raise HTTPException(status_code=409, detail={"code": "snapshot_not_draft"})
    if snapshot.revision != expected_revision:
        raise StaleRevision("snapshot revision is stale")
    if _utc(snapshot.expires_at) <= datetime.now(UTC):
        snapshot.status = "EXPIRED"
        raise HTTPException(status_code=409, detail={"code": "snapshot_expired"})


def source_router(session_factory: Callable[[], Session]) -> APIRouter:
    router = APIRouter(prefix="/api/sources")

    @router.post("/snapshots", status_code=201, response_model=SnapshotResponse)
    def create_snapshot(
        request: SnapshotCreateRequest, credentials: BearerCredentials
    ) -> SnapshotResponse:
        with session_factory() as session, session.begin():
            authenticated = require_authenticated_worker(session, credentials)
            if authenticated.id != request.worker_id:
                raise HTTPException(
                    status_code=403, detail={"code": "snapshot_worker_mismatch"}
                )
            snapshot = SourceSnapshot(
                worker_id=authenticated.id,
                source_kind=request.source_kind,
                source_volume_identity=request.source_volume_identity,
                expires_at=_utc(request.expires_at),
            )
            session.add(snapshot)
            session.flush()
            return _response(snapshot)

    @router.post("/snapshots/{snapshot_id}/entries", response_model=SnapshotResponse)
    def append_entries(
        snapshot_id: str,
        request: SnapshotEntriesRequest,
        credentials: BearerCredentials,
    ) -> SnapshotResponse:
        with session_factory() as session, session.begin():
            snapshot = _owned_snapshot(
                session, snapshot_id, request.worker_id, credentials
            )
            try:
                _draft(snapshot, request.revision)
            except StaleRevision as error:
                raise HTTPException(
                    status_code=409, detail={"code": "stale_snapshot_revision"}
                ) from error
            existing = set(
                session.scalars(
                    select(SourceSnapshotEntry.source_rel_path).where(
                        SourceSnapshotEntry.snapshot_id == snapshot.id
                    )
                )
            )
            entries = _unique_entries(request.entries, existing)
            session.add_all(
                [
                    SourceSnapshotEntry(
                        snapshot_id=snapshot.id,
                        source_rel_path=entry.source_rel_path,
                        size_bytes=entry.size_bytes,
                        mtime_ns=entry.mtime_ns,
                        file_identity=entry.file_identity,
                        pair_status=entry.pair_status,
                    )
                    for entry in entries
                ]
            )
            snapshot.revision += 1
            session.flush()
            return _response(snapshot)

    @router.post("/snapshots/{snapshot_id}/finalize", response_model=SnapshotResponse)
    def finalize_snapshot(
        snapshot_id: str,
        request: SnapshotFinalizeRequest,
        credentials: BearerCredentials,
    ) -> SnapshotResponse:
        with session_factory() as session, session.begin():
            snapshot = _owned_snapshot(
                session, snapshot_id, request.worker_id, credentials
            )
            try:
                _draft(snapshot, request.revision)
            except StaleRevision as error:
                raise HTTPException(
                    status_code=409, detail={"code": "stale_snapshot_revision"}
                ) from error
            entries = session.scalars(
                select(SourceSnapshotEntry).where(
                    SourceSnapshotEntry.snapshot_id == snapshot.id
                )
            ).all()
            if len(entries) != request.declared_item_count:
                raise HTTPException(
                    status_code=409, detail={"code": "snapshot_count_mismatch"}
                )
            snapshot.declared_item_count = len(entries)
            snapshot.source_fingerprint = _fingerprint(snapshot, entries)
            snapshot.status = "FINALIZED"
            snapshot.revision += 1
            session.flush()
            return _response(snapshot)

    return router


def _unique_entries(
    requested: list[SnapshotEntryRequest], existing: set[str]
) -> list[SnapshotEntryRequest]:
    seen = set(existing)
    for entry in requested:
        if entry.source_rel_path in seen:
            raise HTTPException(
                status_code=409, detail={"code": "snapshot_entry_conflict"}
            )
        seen.add(entry.source_rel_path)
    return requested
