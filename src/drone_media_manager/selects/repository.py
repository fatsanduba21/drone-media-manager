"""Generate suggestions, preserve reviews, and export verified originals."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from drone_media_manager.catalog.downloads import resolve_original
from drone_media_manager.config import ServerSettings
from drone_media_manager.db.models.catalog import AssetFile, CatalogAsset
from drone_media_manager.db.models.core import AuditEvent, Job
from drone_media_manager.db.models.ingest import Trip
from drone_media_manager.editorial.models import EditorialField
from drone_media_manager.grouping.models import LocationGroup
from drone_media_manager.movement.models import MovementAnalysis, MovementReview
from drone_media_manager.scoring.repository import JOB_KIND as SCORE_JOB_KIND
from drone_media_manager.scoring.repository import job_data
from drone_media_manager.selects.models import SelectCandidate
from drone_media_manager.selects.service import ALGORITHM_VERSION, recommended_assets
from drone_media_manager.time import utc_now

EXPORT_KIND = "EXPORT_SELECTS"


def _latest_score(
    session: Session, trip_id: str, profile: str
) -> dict[str, Any] | None:
    job = session.scalar(
        select(Job)
        .where(
            Job.kind == SCORE_JOB_KIND,
            Job.status == "COMPLETE",
            func.json_extract(Job.payload_json, "$.trip_id") == trip_id,
            func.json_extract(Job.payload_json, "$.profile") == profile,
        )
        .order_by(Job.created_at.desc(), Job.id.desc())
        .limit(1)
    )
    if job is None:
        return None
    data = job_data(session, job)
    return data if not data["stale"] else None


def generate_candidates(session: Session, trip_id: str, profile: str) -> int:
    if session.get(Trip, trip_id) is None:
        raise ValueError("trip_not_found")
    score = _latest_score(session, trip_id, profile)
    ranked = score["results"] if score else []
    by_id = {row["asset_id"]: row for row in ranked}
    suggested = recommended_assets(ranked)
    assets = session.scalars(
        select(CatalogAsset)
        .where(CatalogAsset.trip_id == trip_id)
        .order_by(CatalogAsset.asset_id)
    ).all()
    ids = [asset.id for asset in assets]
    fields = {
        (field.catalog_asset_id, field.kind): field.value
        for field in session.scalars(
            select(EditorialField).where(EditorialField.catalog_asset_id.in_(ids))
        )
    }
    analyses = {
        row.catalog_asset_id: row
        for row in session.scalars(
            select(MovementAnalysis).where(
                MovementAnalysis.catalog_asset_id.in_(ids),
                MovementAnalysis.superseded_at.is_(None),
            )
        )
    }
    reviews: dict[str, list[MovementReview]] = {}
    for row in session.scalars(
        select(MovementReview).where(
            MovementReview.catalog_asset_id.in_(ids), MovementReview.start_ms >= 0
        )
    ):
        reviews.setdefault(row.catalog_asset_id, []).append(row)
    existing = {
        (row.catalog_asset_id, row.proposed_start_ms, row.proposed_end_ms): row
        for row in session.scalars(
            select(SelectCandidate).where(SelectCandidate.catalog_asset_id.in_(ids))
        )
    }
    for candidate in existing.values():
        if candidate.status == "PENDING":
            candidate.active = False

    def add(
        asset: CatalogAsset,
        start: int,
        end: int,
        movement: str | None,
        reason: str,
        is_suggested: bool,
    ) -> None:
        key = asset.id, start, end
        row = existing.get(key)
        if row is None:
            row = SelectCandidate(
                catalog_asset_id=asset.id,
                proposed_start_ms=start,
                proposed_end_ms=end,
                status="PENDING",
                reason=reason,
                algorithm_version=ALGORITHM_VERSION,
            )
            session.add(row)
            existing[key] = row
        if row.status == "PENDING":
            row.active, row.suggested, row.reason, row.score = (
                True,
                is_suggested,
                reason,
                by_id.get(asset.id, {}).get("editorial_score"),
            )
            row.movement = movement
            row.subject = fields.get((asset.id, "SUBJECT"))
            row.people = fields.get((asset.id, "PEOPLE"), asset.people)
            row.algorithm_version = ALGORITHM_VERSION
        else:
            row.active = True  # Human choices survive reprocessing.

    for asset in assets:
        segments: list[tuple[int, int, str, str]] = []
        if asset.media_type == "VIDEO" and asset.duration_ms:
            for row in sorted(
                reviews.get(asset.id, []), key=lambda r: (r.start_ms, r.end_ms)
            ):
                if (
                    row.value
                    and row.value.upper() != "UNKNOWN"
                    and 0 <= row.start_ms < row.end_ms <= asset.duration_ms
                ):
                    segments.append(
                        (
                            row.start_ms,
                            row.end_ms,
                            row.value,
                            "confirmed_movement_segment",
                        )
                    )
            if not segments and not reviews.get(asset.id) and asset.id in analyses:
                for item in json.loads(analyses[asset.id].segments_json):
                    start, end, movement = (
                        item.get("start_ms"),
                        item.get("end_ms"),
                        item.get("value"),
                    )
                    if (
                        isinstance(start, int)
                        and isinstance(end, int)
                        and isinstance(movement, str)
                        and movement.upper() != "UNKNOWN"
                        and 0 <= start < end <= asset.duration_ms
                    ):
                        segments.append(
                            (start, end, movement, "suggested_movement_segment")
                        )
        top = (
            max(segments, key=lambda item: (item[1] - item[0], -item[0]))
            if segments
            else None
        )
        add(
            asset,
            -1,
            -1,
            asset.movement,
            "ranked_whole_take" if asset.id in suggested else "manual_or_similar_take",
            asset.id in suggested and top is None,
        )
        for start, end, movement, reason in segments:
            add(
                asset,
                start,
                end,
                movement,
                reason,
                asset.id in suggested and top == (start, end, movement, reason),
            )
    session.flush()
    return sum(row.active for row in existing.values())


def candidates_for_trip(session: Session, trip_id: str) -> list[dict[str, Any]]:
    rows = session.execute(
        select(SelectCandidate, CatalogAsset.asset_id, CatalogAsset.duration_ms)
        .join(CatalogAsset, CatalogAsset.id == SelectCandidate.catalog_asset_id)
        .where(CatalogAsset.trip_id == trip_id, SelectCandidate.active.is_(True))
        .order_by(
            SelectCandidate.suggested.desc(),
            SelectCandidate.score.desc(),
            CatalogAsset.asset_id,
            SelectCandidate.proposed_start_ms,
        )
    ).all()
    return [
        {
            "id": row.id,
            "asset_id": row.catalog_asset_id,
            "public_asset_id": asset_id,
            "duration_ms": duration,
            "proposed_start_ms": row.proposed_start_ms,
            "proposed_end_ms": row.proposed_end_ms,
            "start_ms": row.final_start_ms if row.status == "INCLUDE" else None,
            "end_ms": row.final_end_ms if row.status == "INCLUDE" else None,
            "status": row.status,
            "suggested": row.suggested,
            "reason": row.reason,
            "score": row.score,
            "movement": row.movement,
            "subject": row.subject,
            "people": row.people,
            "algorithm_version": row.algorithm_version,
        }
        for row, asset_id, duration in rows
    ]


def review_candidate(
    session: Session,
    candidate_id: str,
    status: str,
    start_ms: int | None,
    end_ms: int | None,
    actor: str,
) -> SelectCandidate:
    row = session.get(SelectCandidate, candidate_id)
    if row is None or not row.active:
        raise ValueError("select_candidate_not_found")
    asset = session.get(CatalogAsset, row.catalog_asset_id)
    assert asset is not None
    if status not in {"PENDING", "INCLUDE", "REJECT"}:
        raise ValueError("invalid_select_status")
    if status != "INCLUDE" and (start_ms is not None or end_ms is not None):
        raise ValueError("invalid_select_interval")
    if status == "INCLUDE":
        if start_ms is None and end_ms is None:
            start_ms, end_ms = row.proposed_start_ms, row.proposed_end_ms
        if (start_ms, end_ms) != (-1, -1) and (
            asset.media_type != "VIDEO"
            or asset.duration_ms is None
            or start_ms is None
            or end_ms is None
            or not 0 <= start_ms < end_ms <= asset.duration_ms
        ):
            raise ValueError("invalid_select_interval")
    before = {
        "status": row.status,
        "start_ms": row.final_start_ms,
        "end_ms": row.final_end_ms,
    }
    row.status = status
    row.final_start_ms = None if start_ms in (None, -1) else start_ms
    row.final_end_ms = None if end_ms in (None, -1) else end_ms
    row.actor = actor
    session.add(
        AuditEvent(
            actor=actor,
            action="select.review",
            entity_type="select_candidate",
            entity_id=row.id,
            result="accepted",
            details_json=json.dumps(
                {
                    "before": before,
                    "after": {
                        "status": status,
                        "start_ms": row.final_start_ms,
                        "end_ms": row.final_end_ms,
                    },
                }
            ),
            correlation_id=str(uuid4()),
        )
    )
    session.flush()
    return row


def enqueue_export(session: Session, trip_id: str, mode: str) -> Job:
    with session.begin():
        session.execute(text("BEGIN IMMEDIATE"))
        if session.get(Trip, trip_id) is None:
            raise ValueError("trip_not_found")
        if mode not in {"FAST", "ACCURATE"}:
            raise ValueError("invalid_export_mode")
        chosen = session.execute(
            select(
                SelectCandidate.id,
                SelectCandidate.final_start_ms,
                SelectCandidate.final_end_ms,
            )
            .join(CatalogAsset, CatalogAsset.id == SelectCandidate.catalog_asset_id)
            .where(
                CatalogAsset.trip_id == trip_id,
                SelectCandidate.active.is_(True),
                SelectCandidate.status == "INCLUDE",
            )
            .order_by(CatalogAsset.asset_id, SelectCandidate.proposed_start_ms)
        ).all()
        if not chosen:
            raise ValueError("selects_empty")
        active = session.scalar(
            select(Job).where(
                Job.kind == EXPORT_KIND,
                Job.status.in_(("PENDING", "RUNNING")),
                func.json_extract(Job.payload_json, "$.trip_id") == trip_id,
            )
        )
        if active:
            return active
        job = Job(
            kind=EXPORT_KIND,
            status="PENDING",
            payload_json=json.dumps(
                {
                    "trip_id": trip_id,
                    "mode": mode,
                    "candidate_ids": [row.id for row in chosen],
                    "decisions": {
                        row.id: [row.final_start_ms, row.final_end_ms] for row in chosen
                    },
                    "algorithm_version": ALGORITHM_VERSION,
                }
            ),
        )
        session.add(job)
        session.flush()
    return job


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _render_segment(
    source: Path, target: Path, start_ms: int, end_ms: int, mode: str
) -> None:
    start, duration = f"{start_ms / 1000:.3f}", f"{(end_ms - start_ms) / 1000:.3f}"
    base = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
    if mode == "FAST":
        args = [
            *base,
            "-ss",
            start,
            "-i",
            str(source),
            "-t",
            duration,
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-c",
            "copy",
            "-avoid_negative_ts",
            "make_zero",
            str(target),
        ]
    else:
        args = [
            *base,
            "-i",
            str(source),
            "-ss",
            start,
            "-t",
            duration,
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(target),
        ]
    result = subprocess.run(
        args, capture_output=True, text=True, check=False, timeout=3600
    )
    if result.returncode or not target.is_file() or target.stat().st_size == 0:
        raise RuntimeError("ffmpeg_failed")


def export_job(
    sessions: Callable[[], Session], settings: ServerSettings, job_id: str
) -> None:
    root = settings.selects_root
    assert root is not None
    work: Path | None = None
    try:
        with sessions() as session, session.begin():
            session.execute(text("BEGIN IMMEDIATE"))
            job = session.get(Job, job_id)
            if job is None or job.kind != EXPORT_KIND or job.status != "PENDING":
                return
            payload = json.loads(job.payload_json)
            payload["started_at"] = utc_now().isoformat()
            job.status, job.attempts, job.payload_json = (
                "RUNNING",
                job.attempts + 1,
                json.dumps(payload),
            )
        with sessions() as session:
            trip = session.get(Trip, payload["trip_id"])
            assert trip is not None
            originals = []
            for candidate_id in payload["candidate_ids"]:
                candidate = session.get(SelectCandidate, candidate_id)
                if (
                    candidate is None
                    or not candidate.active
                    or candidate.status != "INCLUDE"
                    or [candidate.final_start_ms, candidate.final_end_ms]
                    != payload["decisions"][candidate_id]
                ):
                    raise ValueError("selection_changed")
                asset = session.get(CatalogAsset, candidate.catalog_asset_id)
                if asset is None or asset.trip_id != trip.id:
                    raise ValueError("selection_changed")
                if candidate.final_start_ms is not None and (
                    asset.media_type != "VIDEO"
                    or asset.duration_ms is None
                    or candidate.final_end_ms is None
                    or not 0
                    <= candidate.final_start_ms
                    < candidate.final_end_ms
                    <= asset.duration_ms
                ):
                    raise ValueError("selection_changed")
                file = session.scalar(
                    select(AssetFile).where(
                        AssetFile.catalog_asset_id == asset.id,
                        AssetFile.role == "ORIGINAL",
                    )
                )
                original = resolve_original(session, settings, asset)
                if file is None or _sha(original.path) != file.sha256:
                    raise ValueError("source_hash_mismatch")
                originals.append((candidate, asset, original, file.sha256))
            root.mkdir(parents=True, exist_ok=True)
            work = root / f".building-{uuid4().hex}"
            if not work.resolve(strict=False).is_relative_to(root.resolve()):
                raise ValueError("invalid_export_path")
            (work / "SELECTS").mkdir(parents=True)
            manifest_rows = []
            for index, (candidate, asset, original, expected_hash) in enumerate(
                originals, 1
            ):
                output_name = (
                    f"{Path(original.filename).stem}.mp4"
                    if candidate.final_start_ms is not None
                    and payload["mode"] == "ACCURATE"
                    else original.filename
                )
                name = f"{index:03d}_{output_name}"
                target = work / "SELECTS" / name
                if candidate.final_start_ms is None:
                    shutil.copyfile(original.path, target)
                    if _sha(target) != expected_hash:
                        raise ValueError("copied_hash_mismatch")
                else:
                    assert candidate.final_end_ms is not None
                    _render_segment(
                        original.path,
                        target,
                        candidate.final_start_ms,
                        candidate.final_end_ms,
                        payload["mode"],
                    )
                if _sha(original.path) != expected_hash:
                    raise ValueError("source_changed_during_export")
                group = (
                    session.get(LocationGroup, asset.location_group_id)
                    if asset.location_group_id
                    else None
                )
                manifest_rows.append(
                    {
                        "asset_id": asset.asset_id,
                        "filename": name,
                        "source_sha256": expected_hash,
                        "output_sha256": _sha(target),
                        "start_ms": candidate.final_start_ms,
                        "end_ms": candidate.final_end_ms,
                        "score": candidate.score,
                        "location": group.name_final if group else None,
                        "movement": candidate.movement,
                        "subject": candidate.subject,
                        "people": candidate.people,
                        "reason": candidate.reason,
                        "selected_final": True,
                    }
                )
                with sessions() as progress_session, progress_session.begin():
                    progress_job = progress_session.get(Job, job_id)
                    assert progress_job is not None
                    progress_job.progress = index / len(originals) * 0.95
        manifest = {
            "trip_id": payload["trip_id"],
            "mode": payload["mode"],
            "algorithm_version": ALGORITHM_VERSION,
            "selects": manifest_rows,
        }
        (work / "selects_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        with (work / "selects.csv").open(
            "w", encoding="utf-8-sig", newline=""
        ) as stream:
            writer = csv.DictWriter(stream, fieldnames=list(manifest_rows[0]))
            writer.writeheader()
            writer.writerows(manifest_rows)
        final = root / f"selects-{uuid4().hex}"
        work.rename(final)
        work = None
        with sessions() as session, session.begin():
            job = session.get(Job, job_id)
            assert job is not None
            payload.update(
                folder=str(final),
                count=len(manifest_rows),
                finished_at=utc_now().isoformat(),
            )
            job.status, job.progress, job.payload_json = (
                "COMPLETE",
                1,
                json.dumps(payload),
            )
    except Exception:  # noqa: BLE001 -- failed job exposes no paths or ffmpeg output
        with sessions() as session, session.begin():
            job = session.get(Job, job_id)
            if job is not None:
                payload = json.loads(job.payload_json)
                payload["finished_at"] = utc_now().isoformat()
                job.status, job.error, job.payload_json = (
                    "FAILED",
                    "select_export_failed",
                    json.dumps(payload),
                )
    finally:
        if (
            work is not None
            and work.resolve(strict=False).is_relative_to(root.resolve(strict=False))
            and work.exists()
        ):
            shutil.rmtree(work)


def interrupt_jobs(sessions: Callable[[], Session]) -> None:
    with sessions() as session, session.begin():
        for job in session.scalars(
            select(Job).where(
                Job.kind == EXPORT_KIND, Job.status.in_(("PENDING", "RUNNING"))
            )
        ):
            payload = json.loads(job.payload_json)
            payload["finished_at"] = utc_now().isoformat()
            job.status, job.error, job.payload_json = (
                "INTERRUPTED",
                "server_restarted_retry_export",
                json.dumps(payload),
            )
