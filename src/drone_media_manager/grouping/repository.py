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


def ordered_assets(session: Session, trip_id: str) -> list[CatalogAsset]:
    """Return stable editorial order by natural original filename."""
    rows = session.execute(
        select(CatalogAsset, AssetFile)
        .join(AssetFile, AssetFile.catalog_asset_id == CatalogAsset.id)
        .where(CatalogAsset.trip_id == trip_id, AssetFile.role == "ORIGINAL")
    ).all()
    return [
        asset
        for asset, original in sorted(
            rows,
            key=lambda pair: (
                natural_key(Path(pair[1].rel_path).name),
                pair[1].rel_path.casefold(),
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
    if not asset.capture_date or asset.capture_date_source in (None, "unknown"):
        return None
    try:
        return datetime.fromisoformat(asset.capture_date)
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
    group_id: str | None = None,
    actor: str = "human",
) -> LocationGroup:
    """Assign one inclusive, contiguous range; group_id replaces its old range."""
    assets = ordered_assets(session, trip_id)
    positions = {asset.id: index for index, asset in enumerate(assets)}
    if start_asset_id not in positions or end_asset_id not in positions:
        raise ValueError("asset_not_in_trip")
    start, end = positions[start_asset_id], positions[end_asset_id]
    if start > end:
        raise ValueError("reversed_range")
    target = group_id or "__new_group__"
    predicted = [
        None
        if group_id is not None and asset.location_group_id == group_id
        else asset.location_group_id
        for asset in assets
    ]
    predicted[start : end + 1] = [target] * (end - start + 1)
    for other in {value for value in predicted if value is not None}:
        indices = [index for index, value in enumerate(predicted) if value == other]
        if indices[-1] - indices[0] + 1 != len(indices):
            raise ValueError("would_split_group")
    if group_id is None:
        value = (name or "").strip()
        if not value or len(value) > 255:
            raise ValueError("invalid_group_name")
        group = LocationGroup(
            trip_id=trip_id, name_final=value, name_source="HUMAN", name_locked=True
        )
        session.add(group)
        session.flush()
    else:
        existing = session.get(LocationGroup, group_id)
        if existing is None or existing.trip_id != trip_id:
            raise ValueError("group_not_in_trip")
        group = existing
        for asset in assets:
            if asset.location_group_id == group_id:
                asset.location_group_id = None
        if name is not None:
            value = name.strip()
            if not value or len(value) > 255:
                raise ValueError("invalid_group_name")
            group.name_final = value
            group.name_source = "HUMAN"
            group.name_locked = True
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
                    "source": "HUMAN",
                    "locked": True,
                },
                sort_keys=True,
            ),
            correlation_id=str(uuid4()),
        )
    )
    session.flush()
    return group
