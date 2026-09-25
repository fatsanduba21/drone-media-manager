"""Local analysis jobs and audited human decisions; originals are read-only."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from dataclasses import asdict
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from drone_media_manager.catalog.importer import resolve_omv_path
from drone_media_manager.config import ServerSettings
from drone_media_manager.db.models.catalog import AssetFile, CatalogAsset
from drone_media_manager.db.models.core import AuditEvent, Job
from drone_media_manager.db.models.ingest import Trip
from drone_media_manager.grouping.repository import MAX_SRT_BYTES
from drone_media_manager.grouping.telemetry import TelemetrySample, parse_samples
from drone_media_manager.movement.classifier import (
    ALGORITHM_VERSION,
    Suggestion,
    classify,
    segment_track,
)
from drone_media_manager.movement.models import MovementAnalysis, MovementReview
from drone_media_manager.time import utc_now

PARSER_VERSION = "srt-motion-v1"
JOB_KIND = "CLASSIFY_MOVEMENT"


def _samples(
    session: Session, settings: ServerSettings, asset_id: str
) -> tuple[list[TelemetrySample], str | None]:
    srt = session.scalar(
        select(AssetFile).where(
            AssetFile.catalog_asset_id == asset_id, AssetFile.role == "SRT"
        )
    )
    if srt is None or srt.availability_status in {"HASH_MISMATCH", "UNVERIFIED"}:
        return [], None
    cached = session.scalar(
        select(MovementAnalysis)
        .where(
            MovementAnalysis.catalog_asset_id == asset_id,
            MovementAnalysis.source_sha256 == srt.sha256,
            MovementAnalysis.parser_version == PARSER_VERSION,
        )
        .order_by(MovementAnalysis.created_at.desc())
        .limit(1)
    )
    if cached and cached.samples_json != "[]":
        return [
            TelemetrySample(**item) for item in json.loads(cached.samples_json)
        ], srt.sha256
    try:
        path = resolve_omv_path(settings.omv_root, srt.rel_path)
        with path.open("rb") as handle:
            content = handle.read(MAX_SRT_BYTES + 1)
        if (
            len(content) > MAX_SRT_BYTES
            or hashlib.sha256(content).hexdigest() != srt.sha256
        ):
            return [], None
    except (OSError, ValueError):
        return [], None
    return parse_samples(content.decode("utf-8-sig", errors="replace")), srt.sha256


def analyze_asset(
    session: Session, settings: ServerSettings, asset_id: str
) -> MovementAnalysis:
    asset = session.get(CatalogAsset, asset_id)
    if asset is None:
        raise ValueError("asset_not_found")
    samples, source_hash = (
        _samples(session, settings, asset_id)
        if asset.media_type == "VIDEO"
        else ([], None)
    )
    review = session.scalar(
        select(MovementReview).where(
            MovementReview.catalog_asset_id == asset_id, MovementReview.start_ms == -1
        )
    )
    anchor = (
        (review.anchor_lat, review.anchor_lon)
        if review and review.anchor_lat is not None and review.anchor_lon is not None
        else None
    )
    suggestion = (
        classify(samples, anchor=anchor)
        if samples
        else Suggestion("UNKNOWN", 0, {"reason": "no_usable_srt"})
    )
    segments = segment_track(samples, duration_ms=asset.duration_ms, anchor=anchor)
    for previous in session.scalars(
        select(MovementAnalysis).where(
            MovementAnalysis.catalog_asset_id == asset_id,
            MovementAnalysis.superseded_at.is_(None),
        )
    ):
        previous.superseded_at = utc_now()
    # ponytail: samples are retained per analysis for audit; use a hash-addressed
    # cache if repeated analyses make the local catalog too large.
    row = MovementAnalysis(
        catalog_asset_id=asset_id,
        value=suggestion.value,
        confidence=suggestion.confidence,
        algorithm_version=ALGORITHM_VERSION,
        parser_version=PARSER_VERSION,
        source_sha256=source_hash,
        evidence_json=json.dumps(suggestion.evidence),
        samples_json=json.dumps([asdict(sample) for sample in samples]),
        segments_json=json.dumps(
            [
                {"start_ms": start, "end_ms": end, **result.data()}
                for start, end, result in segments
            ]
        ),
    )
    session.add(row)
    session.flush()
    return row


def review_movement(
    session: Session,
    asset_id: str,
    value: str | None,
    *,
    actor: str,
    start_ms: int = -1,
    end_ms: int = -1,
    anchor: tuple[float, float] | None = None,
) -> MovementReview:
    asset = session.get(CatalogAsset, asset_id)
    if asset is None:
        raise ValueError("asset_not_found")
    if value is not None:
        value = value.strip()
        if not value or len(value) > 64 or any(ord(c) < 32 for c in value):
            raise ValueError("invalid_movement")
    if (start_ms, end_ms) != (-1, -1):
        if (
            asset.media_type != "VIDEO"
            or asset.duration_ms is None
            or not 0 <= start_ms < end_ms <= asset.duration_ms
        ):
            raise ValueError("invalid_segment")
        if session.scalar(
            select(MovementReview.id).where(
                MovementReview.catalog_asset_id == asset_id,
                MovementReview.start_ms >= 0,
                MovementReview.start_ms < end_ms,
                MovementReview.end_ms > start_ms,
                ~(
                    (MovementReview.start_ms == start_ms)
                    & (MovementReview.end_ms == end_ms)
                ),
            )
        ):
            raise ValueError("overlapping_confirmed_segment")
    if anchor is not None and (
        not all(math.isfinite(n) for n in anchor)
        or not -90 <= anchor[0] <= 90
        or not -180 <= anchor[1] <= 180
        or start_ms != -1
    ):
        raise ValueError("invalid_reference")
    row = session.scalar(
        select(MovementReview).where(
            MovementReview.catalog_asset_id == asset_id,
            MovementReview.start_ms == start_ms,
            MovementReview.end_ms == end_ms,
        )
    )
    if row is None:
        row = MovementReview(
            catalog_asset_id=asset_id, start_ms=start_ms, end_ms=end_ms, actor=actor
        )
        session.add(row)
    if value is not None:
        row.value = value
        if start_ms == -1:
            asset.movement = value
    if anchor is not None:
        row.anchor_lat, row.anchor_lon = anchor
    row.actor, row.source, row.locked, row.updated_at = actor, "HUMAN", True, utc_now()
    session.flush()
    session.add(
        AuditEvent(
            actor=actor,
            action="movement.reference" if anchor else "movement.confirm",
            entity_type="catalog_asset",
            entity_id=asset_id,
            result="accepted",
            details_json=json.dumps(
                {
                    "value": row.value,
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                    "anchor": anchor,
                    "source": "HUMAN",
                    "locked": True,
                }
            ),
            correlation_id=str(uuid4()),
        )
    )
    return row


def enqueue_job(session: Session, trip_id: str) -> Job:
    """Own a short transaction; duplicate clicks reuse the active trip job."""
    with session.begin():
        session.execute(text("BEGIN IMMEDIATE"))
        if session.get(Trip, trip_id) is None:
            raise ValueError("trip_not_found")
        for job in session.scalars(
            select(Job).where(
                Job.kind == JOB_KIND, Job.status.in_(("PENDING", "RUNNING"))
            )
        ):
            if json.loads(job.payload_json)["trip_id"] == trip_id:
                return job
        job = Job(
            kind=JOB_KIND,
            payload_json=json.dumps(
                {"trip_id": trip_id, "algorithm_version": ALGORITHM_VERSION}
            ),
            status="PENDING",
        )
        session.add(job)
        session.flush()
    return job


def run_job(
    sessions: Callable[[], Session], settings: ServerSettings, job_id: str
) -> None:
    try:
        with sessions() as session, session.begin():
            session.execute(text("BEGIN IMMEDIATE"))
            job = session.get(Job, job_id)
            if job is None or job.kind != JOB_KIND or job.status != "PENDING":
                return
            payload = json.loads(job.payload_json)
            job.status, job.attempts = "RUNNING", job.attempts + 1
            payload["started_at"] = utc_now().isoformat()
            job.payload_json = json.dumps(payload)
            ids = list(
                session.scalars(
                    select(CatalogAsset.id).where(
                        CatalogAsset.trip_id == payload["trip_id"]
                    )
                )
            )
        for index, asset_id in enumerate(ids):
            with sessions() as session, session.begin():
                analyze_asset(session, settings, asset_id)
                job = session.get(Job, job_id)
                assert job is not None
                job.progress = (index + 1) / len(ids)
        with sessions() as session, session.begin():
            job = session.get(Job, job_id)
            assert job is not None
            job.status, job.progress = "COMPLETE", 1
            payload["finished_at"] = utc_now().isoformat()
            job.payload_json = json.dumps(payload)
    except Exception:  # noqa: BLE001 -- persist a failed background job, without leaking paths/credentials
        with sessions() as session, session.begin():
            job = session.get(Job, job_id)
            if job is not None:
                job.status, job.error = "FAILED", "movement_analysis_failed"
                payload = json.loads(job.payload_json)
                payload["finished_at"] = utc_now().isoformat()
                job.payload_json = json.dumps(payload)


def interrupt_jobs(sessions: Callable[[], Session]) -> None:
    """Single Mac server: a previous process cannot continue its local tasks."""
    with sessions() as session, session.begin():
        for job in session.scalars(
            select(Job).where(
                Job.kind == JOB_KIND, Job.status.in_(("PENDING", "RUNNING"))
            )
        ):
            job.status, job.error = "INTERRUPTED", "server_restarted_retry_analysis"
