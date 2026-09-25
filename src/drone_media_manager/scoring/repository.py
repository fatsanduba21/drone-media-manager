"""Durable analysis snapshots and editable weights. No media writes."""

from __future__ import annotations

import hashlib
import io
import json
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from PIL import Image
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from drone_media_manager.catalog.importer import resolve_omv_path
from drone_media_manager.config import ServerSettings
from drone_media_manager.db.models.catalog import AssetFile, CatalogAsset, Derivative
from drone_media_manager.db.models.core import AuditEvent, Job
from drone_media_manager.db.models.ingest import Trip
from drone_media_manager.editorial.models import EditorialField
from drone_media_manager.movement.repository import _samples
from drone_media_manager.scoring.models import ScoringProfile
from drone_media_manager.scoring.service import (
    ALGORITHM_VERSION,
    COMPONENTS,
    DEFAULT_PROFILES,
    compare_takes,
    image_metrics,
    motion_metrics,
    validate_weights,
    weighted_score,
)
from drone_media_manager.time import utc_now

JOB_KIND = "CALCULATE_SCORE"
MAX_THUMBNAIL_BYTES = 10 * 1024 * 1024


def profile_weights(session: Session, profile: str) -> dict[str, float]:
    if profile not in DEFAULT_PROFILES:
        raise ValueError("score_profile_not_found")
    row = session.get(ScoringProfile, profile)
    return validate_weights(
        json.loads(row.weights_json) if row else DEFAULT_PROFILES[profile]
    )


def save_profile(
    session: Session, profile: str, weights: dict[str, float], actor: str
) -> dict[str, float]:
    session.execute(text("BEGIN IMMEDIATE"))
    before = profile_weights(session, profile)
    weights = validate_weights(weights)
    row = session.get(ScoringProfile, profile)
    if row is None:
        row = ScoringProfile(id=profile)
        session.add(row)
    row.weights_json = json.dumps(weights)
    session.add(
        AuditEvent(
            actor=actor,
            action="scoring.profile.update",
            entity_type="scoring_profile",
            entity_id=profile,
            result="accepted",
            details_json=json.dumps({"before": before, "after": weights}),
            correlation_id=str(uuid4()),
        )
    )
    return weights


def inputs(session: Session, trip_id: str) -> list[dict[str, Any]]:
    assets = session.scalars(
        select(CatalogAsset)
        .where(CatalogAsset.trip_id == trip_id)
        .order_by(CatalogAsset.id)
    ).all()
    ids = [asset.id for asset in assets]
    files = {
        (f.catalog_asset_id, f.role): f
        for f in session.scalars(
            select(AssetFile).where(AssetFile.catalog_asset_id.in_(ids))
        )
    }
    thumbnails = {
        d.catalog_asset_id: d
        for d in session.scalars(
            select(Derivative).where(
                Derivative.catalog_asset_id.in_(ids), Derivative.kind == "THUMBNAIL"
            )
        )
    }
    fields = {
        (f.catalog_asset_id, f.kind): f.value
        for f in session.scalars(
            select(EditorialField).where(EditorialField.catalog_asset_id.in_(ids))
        )
    }
    rows = []
    for asset in assets:
        original, srt = files.get((asset.id, "ORIGINAL")), files.get((asset.id, "SRT"))
        thumb = thumbnails.get(asset.id)
        rows.append(
            {
                "asset_id": asset.id,
                "public_asset_id": asset.asset_id,
                "filename": original.rel_path.replace("\\", "/").rsplit("/", 1)[-1]
                if original
                else asset.asset_id,
                "context": {
                    "trip_id": trip_id,
                    "location_group_id": asset.location_group_id,
                    "movement": asset.movement,
                    "subject": fields.get((asset.id, "SUBJECT")),
                    "media_type": asset.media_type,
                },
                "duration_ms": asset.duration_ms,
                "people": fields.get((asset.id, "PEOPLE"), asset.people),
                "source_sha256": original.sha256 if original else None,
                "srt": {
                    "sha256": srt.sha256,
                    "status": srt.availability_status,
                    "path": srt.rel_path,
                }
                if srt
                else None,
                "thumbnail": {
                    "path": thumb.rel_path,
                    "status": thumb.status,
                    "source_sha256": thumb.source_sha256,
                    "output_sha256": thumb.output_sha256,
                    "version": thumb.profile_version,
                }
                if thumb
                else None,
            }
        )
    return rows


def signature(rows: list[dict[str, Any]]) -> str:
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def score_asset(
    session: Session, settings: ServerSettings, source: dict[str, Any]
) -> dict[str, Any]:
    evidence: dict[str, Any] = {"composition": {"reason": "not_evaluated"}}
    technical, fingerprint = None, None
    thumb = source["thumbnail"]
    if (
        thumb
        and thumb["status"] == "READY"
        and thumb["source_sha256"] == source["source_sha256"]
        and thumb["path"]
        and settings.derivatives_root
    ):
        try:
            path = resolve_omv_path(settings.derivatives_root, thumb["path"])
            with path.open("rb") as handle:
                content = handle.read(MAX_THUMBNAIL_BYTES + 1)
            if (
                len(content) > MAX_THUMBNAIL_BYTES
                or hashlib.sha256(content).hexdigest() != thumb["output_sha256"]
            ):
                raise ValueError("invalid_thumbnail")
            with Image.open(io.BytesIO(content)) as image:
                if image.width * image.height > 4_000_000:
                    raise ValueError("oversized_thumbnail")
                technical, evidence["technical"], fingerprint = image_metrics(image)
        except (OSError, ValueError, Image.DecompressionBombError):
            evidence["technical"] = {"reason": "thumbnail_unavailable_or_invalid"}
    else:
        evidence["technical"] = {"reason": "no_current_thumbnail"}
    samples, srt_hash = (
        _samples(session, settings, source["asset_id"])
        if source["context"]["media_type"] == "VIDEO"
        else ([], None)
    )
    motion, evidence["motion"] = motion_metrics(samples)
    evidence["motion"]["source_sha256"] = srt_hash
    duration = source["duration_ms"]
    duration_score = (
        round(min(100, duration / 100), 1) if duration and duration > 0 else None
    )
    people_score = {"YES": 100.0, "NO": 0.0}.get(source["people"])
    evidence["duration"] = {
        "duration_ms": duration,
        "formula": "min(100, duration_ms / 100); 10 seconds saturates; not useful-duration detection",
    }
    evidence["people"] = {
        "value": source["people"],
        "formula": "YES=100, NO=0; preference for people, not visual quality",
    }
    evidence["uniqueness"] = {
        "formula": "min(100, nearest dHash distance / 32 * 100)",
        "similarity_threshold": 8,
        "scope": "same confirmed context, single thumbnail; candidate only",
    }
    return {
        **source,
        "technical_score": technical,
        "motion_score": motion,
        "composition_score": None,
        "duration_score": duration_score,
        "people_score": people_score,
        "fingerprint": str(fingerprint) if fingerprint is not None else None,
        "evidence": evidence,
    }


def enqueue_job(session: Session, trip_id: str, profile: str) -> Job:
    with session.begin():
        session.execute(text("BEGIN IMMEDIATE"))
        if session.get(Trip, trip_id) is None:
            raise ValueError("trip_not_found")
        weights = profile_weights(session, profile)
        active = session.scalar(
            select(Job).where(
                Job.kind == JOB_KIND,
                Job.status.in_(("PENDING", "RUNNING")),
                func.json_extract(Job.payload_json, "$.trip_id") == trip_id,
                func.json_extract(Job.payload_json, "$.profile") == profile,
            )
        )
        if active:
            return active
        job = Job(
            kind=JOB_KIND,
            status="PENDING",
            payload_json=json.dumps(
                {
                    "trip_id": trip_id,
                    "profile": profile,
                    "weights": weights,
                    "algorithm_version": ALGORITHM_VERSION,
                }
            ),
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
            source = inputs(session, payload["trip_id"])
            payload.update(
                started_at=utc_now().isoformat(), input_signature=signature(source)
            )
            job.status, job.attempts, job.payload_json = (
                "RUNNING",
                job.attempts + 1,
                json.dumps(payload),
            )
        rows = []
        for index, item in enumerate(source):
            with sessions() as session:
                rows.append(score_asset(session, settings, item))
            with sessions() as session, session.begin():
                job = session.get(Job, job_id)
                assert job is not None
                job.progress = (index + 1) / max(1, len(source)) * 0.9
        compare_takes(rows)
        for row in rows:
            row["editorial_score"], row["coverage"] = weighted_score(
                {key: row.get(key + "_score") for key in COMPONENTS}, payload["weights"]
            )
        rows.sort(
            key=lambda row: (
                row["editorial_score"] is None,
                -(row["editorial_score"] or 0),
                row["filename"],
                row["asset_id"],
            )
        )
        with sessions() as session, session.begin():
            job = session.get(Job, job_id)
            assert job is not None
            payload.update(results=rows, finished_at=utc_now().isoformat())
            job.payload_json, job.status, job.progress = (
                json.dumps(payload),
                "COMPLETE",
                1,
            )
    except Exception:  # noqa: BLE001 -- sanitized durable failure, no partial ranking
        with sessions() as session, session.begin():
            job = session.get(Job, job_id)
            if job is not None:
                payload = json.loads(job.payload_json)
                payload["finished_at"] = utc_now().isoformat()
                job.payload_json, job.status, job.error = (
                    json.dumps(payload),
                    "FAILED",
                    "score_analysis_failed",
                )


def interrupt_jobs(sessions: Callable[[], Session]) -> None:
    with sessions() as session, session.begin():
        for job in session.scalars(
            select(Job).where(
                Job.kind == JOB_KIND, Job.status.in_(("PENDING", "RUNNING"))
            )
        ):
            payload = json.loads(job.payload_json)
            payload["finished_at"] = utc_now().isoformat()
            job.payload_json, job.status, job.error = (
                json.dumps(payload),
                "INTERRUPTED",
                "server_restarted_retry_analysis",
            )


def job_data(session: Session, job: Job) -> dict[str, Any]:
    payload = json.loads(job.payload_json)
    stale = job.status == "COMPLETE" and (
        payload.get("input_signature") != signature(inputs(session, payload["trip_id"]))
        or payload["weights"] != profile_weights(session, payload["profile"])
        or payload["algorithm_version"] != ALGORITHM_VERSION
    )
    return {
        **payload,
        "id": job.id,
        "status": job.status,
        "progress": job.progress,
        "error": job.error,
        "stale": stale,
    }
