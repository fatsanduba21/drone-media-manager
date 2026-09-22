"""Localhost-admin confirmation and lookup routes for finalized ingest snapshots."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import PurePosixPath

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from drone_media_manager.api.schemas.ingests import (
    IngestConfirmationRequest,
    IngestResponse,
)
from drone_media_manager.config import ServerSettings, _is_loopback_host
from drone_media_manager.db.models.core import Job
from drone_media_manager.db.models.ingest import (
    IngestItem,
    IngestJob,
    SourceSnapshot,
    SourceSnapshotEntry,
    Trip,
)
from drone_media_manager.domain.enums import IngestItemStatus, IngestStatus, JobStatus


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _require_localhost_admin(settings: ServerSettings) -> None:
    if not _is_loopback_host(settings.bind_host):
        raise HTTPException(
            status_code=403, detail={"code": "localhost_admin_required"}
        )


def _response(ingest: IngestJob) -> IngestResponse:
    return IngestResponse(
        ingest_id=ingest.id,
        status=ingest.status,
        revision=ingest.revision,
        trip_id=ingest.trip_id,
        snapshot_id=ingest.source_snapshot_id,
        bytes_total=ingest.bytes_total,
        bytes_verified=ingest.bytes_verified,
        manifest_status="VERIFIED"
        if ingest.status == IngestStatus.VERIFIED
        else "PENDING",
    )


def ingest_router(
    settings: ServerSettings, session_factory: Callable[[], Session]
) -> APIRouter:
    router = APIRouter(prefix="/api/ingests")

    @router.post("", status_code=201, response_model=IngestResponse)
    def confirm_ingest(request: IngestConfirmationRequest) -> IngestResponse:
        _require_localhost_admin(settings)
        try:
            with session_factory() as session, session.begin():
                snapshot = session.get(SourceSnapshot, request.snapshot_id)
                if snapshot is None:
                    raise HTTPException(
                        status_code=404, detail={"code": "snapshot_not_found"}
                    )
                if snapshot.status != "FINALIZED":
                    raise HTTPException(
                        status_code=409, detail={"code": "snapshot_not_finalized"}
                    )
                if snapshot.revision != request.revision:
                    raise HTTPException(
                        status_code=409, detail={"code": "stale_snapshot_revision"}
                    )
                if _utc(snapshot.expires_at) <= datetime.now(UTC):
                    snapshot.status = "EXPIRED"
                    raise HTTPException(
                        status_code=409, detail={"code": "snapshot_expired"}
                    )
                trip = session.get(Trip, request.trip_id)
                if trip is None:
                    raise HTTPException(
                        status_code=404, detail={"code": "trip_not_found"}
                    )
                assert snapshot.source_fingerprint is not None
                ingest = session.scalar(
                    select(IngestJob).where(
                        IngestJob.trip_id == trip.id,
                        IngestJob.source_fingerprint == snapshot.source_fingerprint,
                    )
                )
                if ingest is not None:
                    return _response(ingest)
                ingest = IngestJob(
                    trip_id=trip.id,
                    source_snapshot_id=snapshot.id,
                    source_kind=snapshot.source_kind,
                    source_volume_identity=snapshot.source_volume_identity,
                    source_fingerprint=snapshot.source_fingerprint,
                    status=IngestStatus.DISCOVERED,
                )
                session.add(ingest)
                session.flush()
                entries = session.scalars(
                    select(SourceSnapshotEntry)
                    .where(SourceSnapshotEntry.snapshot_id == snapshot.id)
                    .order_by(SourceSnapshotEntry.source_rel_path)
                ).all()
                payload_items: list[dict[str, object]] = []
                item_records: list[IngestItem] = []
                for entry in entries:
                    destination = _destination_path(trip, entry)
                    partial = _partial_path(destination, ingest.id)
                    item = IngestItem(
                        ingest_job_id=ingest.id,
                        source_rel_path=entry.source_rel_path,
                        source_size_bytes=entry.size_bytes,
                        source_mtime_ns=entry.mtime_ns,
                        source_file_identity=entry.file_identity,
                        pair_status=entry.pair_status or "VIDEO_WITHOUT_SRT",
                        destination_rel_path=destination,
                        partial_rel_path=partial,
                        status=IngestItemStatus.PENDING,
                    )
                    session.add(item)
                    item_records.append(item)
                    payload_items.append(
                        {
                            "id": item.id,
                            "source_rel_path": entry.source_rel_path,
                            "source_size_bytes": entry.size_bytes,
                            "source_mtime_ns": entry.mtime_ns,
                            "source_file_identity": entry.file_identity,
                            "pair_status": entry.pair_status or "VIDEO_WITHOUT_SRT",
                            "destination_rel_path": destination,
                            "partial_rel_path": partial,
                        }
                    )
                ingest.bytes_total = sum(entry.size_bytes for entry in entries)
                session.flush()
                for item, payload_item in zip(item_records, payload_items, strict=True):
                    payload_item["id"] = item.id
                session.add(
                    Job(
                        kind="ingest",
                        payload_json=json.dumps(
                            {
                                "ingest_id": ingest.id,
                                "snapshot_id": snapshot.id,
                                "worker_id": snapshot.worker_id,
                                "source_kind": snapshot.source_kind,
                                "source_fingerprint": snapshot.source_fingerprint,
                                "items": payload_items,
                            },
                            separators=(",", ":"),
                        ),
                        status=JobStatus.PENDING,
                    )
                )
                session.flush()
                return _response(ingest)
        except IntegrityError as error:
            raise HTTPException(
                status_code=409, detail={"code": "ingest_confirmation_conflict"}
            ) from error

    @router.get("/{ingest_id}", response_model=IngestResponse)
    def get_ingest(ingest_id: str) -> IngestResponse:
        _require_localhost_admin(settings)
        with session_factory() as session:
            ingest = session.get(IngestJob, ingest_id)
            if ingest is None:
                raise HTTPException(
                    status_code=404, detail={"code": "ingest_not_found"}
                )
            return _response(ingest)

    return router


def _destination_path(trip: Trip, entry: SourceSnapshotEntry) -> str:
    return (
        PurePosixPath("trips")
        / trip.slug
        / "00_INBOX_ORIGINALS"
        / PurePosixPath(entry.source_rel_path)
    ).as_posix()


def _partial_path(destination: str, ingest_id: str) -> str:
    final = PurePosixPath(destination)
    return (final.parent / f".{final.name}.{ingest_id}.partial").as_posix()
