"""Database-backed Phase 3A analysis and human range operations."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from drone_media_manager.catalog.importer import resolve_omv_path
from drone_media_manager.config import ServerSettings
from drone_media_manager.db.models.catalog import AssetFile, CatalogAsset
from drone_media_manager.db.models.core import AuditEvent
from drone_media_manager.grouping.models import (
    GroupingSuggestion,
    LocationGroup,
    TelemetryTrack,
)
from drone_media_manager.grouping.service import (
    ALGORITHM_VERSION,
    ClipSignal,
    natural_key,
    suggest_ranges,
)
from drone_media_manager.grouping.telemetry import TelemetrySummary, parse_srt
from drone_media_manager.time import utc_now

PARSER_VERSION = "srt-parser-v1"
MAX_SRT_BYTES = 8 * 1024 * 1024


def ordered_assets(
    session: Session, trip_id: str, *, include_missing: bool = False
) -> list[CatalogAsset]:
    """Return capture order, falling back to date and natural filename."""
    query = select(CatalogAsset, AssetFile)
    if include_missing:
        query = query.outerjoin(
            AssetFile,
            (AssetFile.catalog_asset_id == CatalogAsset.id)
            & (AssetFile.role == "ORIGINAL"),
        )
    else:
        query = query.join(
            AssetFile, AssetFile.catalog_asset_id == CatalogAsset.id
        ).where(AssetFile.role == "ORIGINAL")
    rows = session.execute(query.where(CatalogAsset.trip_id == trip_id)).all()
    return [
        asset
        for asset, original in sorted(
            rows,
            key=lambda pair: (
                pair[0].capture_time
                or (pair[0].capture_date or "9999-12-31") + "T00:00:00",
                natural_key(
                    Path(pair[1].rel_path).name if pair[1] else pair[0].asset_id
                ),
                pair[1].rel_path.casefold() if pair[1] else pair[0].asset_id,
            ),
        )
    ]


def _original_files(session: Session, trip_id: str) -> dict[str, dict[str, AssetFile]]:
    rows = session.execute(
        select(AssetFile, CatalogAsset.trip_id)
        .join(CatalogAsset, CatalogAsset.id == AssetFile.catalog_asset_id)
        .where(CatalogAsset.trip_id == trip_id)
    ).all()
    files: dict[str, dict[str, AssetFile]] = {}
    for row, _ in rows:
        files.setdefault(row.catalog_asset_id, {})[row.role] = row
    return files


def _timestamp(asset: CatalogAsset) -> datetime | None:
    value = asset.capture_time or asset.capture_date
    if not value or asset.capture_date_source in (None, "unknown"):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _summary(
    session: Session,
    settings: ServerSettings,
    asset: CatalogAsset,
    srt: AssetFile | None,
) -> TelemetrySummary:
    if srt is None or srt.availability_status != "AVAILABLE":
        return TelemetrySummary(0)
    cached = session.scalar(
        select(TelemetryTrack).where(TelemetryTrack.catalog_asset_id == asset.id)
    )
    if (
        cached is not None
        and cached.source_sha256 == srt.sha256
        and cached.parser_version == PARSER_VERSION
    ):
        return TelemetrySummary(
            cached.sample_count,
            cached.start_lat,
            cached.start_lon,
            cached.end_lat,
            cached.end_lon,
            cached.centroid_lat,
            cached.centroid_lon,
            cached.start_time,
            cached.end_time,
        )
    path = resolve_omv_path(settings.omv_root, srt.rel_path)
    try:
        if path.stat().st_size > MAX_SRT_BYTES:
            return TelemetrySummary(0)
        summary = parse_srt(path.read_text(encoding="utf-8-sig", errors="replace"))
    except OSError:
        return TelemetrySummary(0)
    row = cached or TelemetryTrack(
        catalog_asset_id=asset.id,
        parser_version=PARSER_VERSION,
        source_sha256=srt.sha256,
        sample_count=0,
    )
    if cached is None:
        session.add(row)
    row.parser_version = PARSER_VERSION
    row.source_sha256 = srt.sha256
    row.sample_count = summary.sample_count
    for field in (
        "start_time",
        "end_time",
        "start_lat",
        "start_lon",
        "end_lat",
        "end_lon",
        "centroid_lat",
        "centroid_lon",
    ):
        setattr(row, field, getattr(summary, field))
    row.updated_at = utc_now()
    return summary


def analyze_trip(
    session: Session, settings: ServerSettings, trip_id: str
) -> list[GroupingSuggestion]:
    """Refresh suggestions without changing any confirmed group or human name."""
    assets = ordered_assets(session, trip_id)
    files = _original_files(session, trip_id)
    clips = []
    for asset in assets:
        original = files[asset.id]["ORIGINAL"]
        telemetry = _summary(session, settings, asset, files[asset.id].get("SRT"))
        clips.append(
            ClipSignal(
                asset.id,
                Path(original.rel_path).name,
                telemetry.start_time or _timestamp(asset),
                telemetry.start_lat,
                telemetry.start_lon,
                telemetry.end_time,
                telemetry.end_lat,
                telemetry.end_lon,
            )
        )
    ranges = suggest_ranges(clips)
    for previous in session.scalars(
        select(GroupingSuggestion).where(
            GroupingSuggestion.trip_id == trip_id,
            GroupingSuggestion.superseded_at.is_(None),
        )
    ):
        previous.superseded_at = utc_now()
    suggestions = []
    for group in ranges:
        row = GroupingSuggestion(
            trip_id=trip_id,
            start_asset_id=group.clips[0].asset_id,
            end_asset_id=group.clips[-1].asset_id,
            algorithm_version=ALGORITHM_VERSION,
            confidence=group.confidence,
            evidence_json=json.dumps(group.evidence, sort_keys=True),
        )
        session.add(row)
        suggestions.append(row)
    session.flush()
    return suggestions


def assign_range(
    session: Session,
    trip_id: str,
    start_asset_id: str,
    end_asset_id: str,
    *,
    name: str | None = None,
    place_id: str | None = None,
    group_id: str | None = None,
    replace_existing: bool = True,
    actor: str = "human",
) -> LocationGroup:
    """Assign an inclusive range, optionally retaining existing group members."""
    assets = ordered_assets(session, trip_id)
    positions = {asset.id: index for index, asset in enumerate(assets)}
    if start_asset_id not in positions or end_asset_id not in positions:
        raise ValueError("asset_not_in_trip")
    start, end = positions[start_asset_id], positions[end_asset_id]
    if start > end:
        raise ValueError("reversed_range")
    if group_id is None:
        value = (name or "").strip()
        if not value or len(value) > 255:
            raise ValueError("invalid_group_name")
        group = LocationGroup(
            trip_id=trip_id,
            name_final=value,
            name_source="GOOGLE_PLACES_CONFIRMED" if place_id else "HUMAN",
            name_locked=True,
            provider_place_id=place_id,
        )
        session.add(group)
        session.flush()
    else:
        existing = session.get(LocationGroup, group_id)
        if existing is None or existing.trip_id != trip_id:
            raise ValueError("group_not_in_trip")
        group = existing
        if replace_existing:
            for asset in assets:
                if asset.location_group_id == group_id:
                    asset.location_group_id = None
        if name is not None:
            value = name.strip()
            if not value or len(value) > 255:
                raise ValueError("invalid_group_name")
            group.name_final = value
            group.name_source = "GOOGLE_PLACES_CONFIRMED" if place_id else "HUMAN"
            group.name_locked = True
            group.provider_place_id = place_id
    for asset in assets[start : end + 1]:
        asset.location_group_id = group.id
    group.updated_at = utc_now()
    session.add(
        AuditEvent(
            actor=actor,
            action="location_group.update" if group_id else "location_group.create",
            entity_type="location_group",
            entity_id=group.id,
            result="accepted",
            details_json=json.dumps(
                {
                    "start_asset_id": start_asset_id,
                    "end_asset_id": end_asset_id,
                    "name_final": group.name_final,
                    "source": group.name_source,
                    "locked": True,
                },
                sort_keys=True,
            ),
            correlation_id=str(uuid4()),
        )
    )
    session.flush()
    return group


def range_center(
    session: Session, trip_id: str, start_asset_id: str, end_asset_id: str
) -> tuple[float, float] | None:
    """Use cached SRT centroids from a valid inclusive editorial range."""
    assets = ordered_assets(session, trip_id)
    positions = {asset.id: index for index, asset in enumerate(assets)}
    if start_asset_id not in positions or end_asset_id not in positions:
        raise ValueError("asset_not_in_trip")
    start, end = positions[start_asset_id], positions[end_asset_id]
    if start > end:
        raise ValueError("reversed_range")
    asset_ids = [asset.id for asset in assets[start : end + 1]]
    tracks = session.scalars(
        select(TelemetryTrack).where(TelemetryTrack.catalog_asset_id.in_(asset_ids))
    ).all()
    points = [
        (track.centroid_lat, track.centroid_lon)
        for track in tracks
        if track.centroid_lat is not None and track.centroid_lon is not None
    ]
    if not points:
        return None
    return (
        sum(point[0] for point in points) / len(points),
        sum(point[1] for point in points) / len(points),
    )


def rename_group(
    session: Session, trip_id: str, group_id: str, name: str, *, actor: str
) -> LocationGroup:
    """Keep group members while replacing the final name with a human edit."""
    group = session.get(LocationGroup, group_id)
    if group is None or group.trip_id != trip_id:
        raise ValueError("group_not_in_trip")
    value = name.strip()
    if not value or len(value) > 255:
        raise ValueError("invalid_group_name")
    group.name_final = value
    group.name_source = "HUMAN"
    group.name_locked = True
    group.provider_place_id = None
    group.updated_at = utc_now()
    session.add(
        AuditEvent(
            actor=actor,
            action="location_group.rename",
            entity_type="location_group",
            entity_id=group.id,
            result="accepted",
            details_json=json.dumps({"name_final": value, "source": "HUMAN"}),
            correlation_id=str(uuid4()),
        )
    )
    session.flush()
    return group
