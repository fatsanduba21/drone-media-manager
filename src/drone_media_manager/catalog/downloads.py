"""Validate registered OMV originals and derive safe editorial download names."""

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from drone_media_manager.catalog.importer import ManifestError, resolve_omv_path
from drone_media_manager.config import ServerSettings
from drone_media_manager.db.models.catalog import AssetFile, CatalogAsset
from drone_media_manager.db.models.ingest import Trip
from drone_media_manager.grouping.models import LocationGroup

_BAD_NAME = set('/\\<>:"|?*')
_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


@dataclass(frozen=True)
class OriginalDownload:
    path: Path
    filename: str
    size_bytes: int
    media_type: str


def safe_filename(raw: str, asset_id: str) -> str:
    """Make a Unicode editorial basename safe across macOS and Windows."""
    normalized = unicodedata.normalize("NFC", raw)
    cleaned = "".join(
        "_" if char in _BAD_NAME or unicodedata.category(char).startswith("C") else char
        for char in normalized
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    stem, extension = os.path.splitext(cleaned)
    stem = stem.strip(" .")[:140]
    extension = extension[:16]
    if not stem or stem.upper() in _RESERVED:
        stem = f"asset-{asset_id[:12]}"
    return f"{stem}{extension}"


def _unavailable() -> HTTPException:
    return HTTPException(status_code=409, detail={"code": "original_unavailable"})


def _editorial_name(session: Session, asset: CatalogAsset, original: AssetFile) -> str:
    if asset.location_group_id:
        group = session.get(LocationGroup, asset.location_group_id)
        if group is not None and group.trip_id == asset.trip_id:
            formats = {
                "YOUTUBE_16X9": "16x9",
                "INSTAGRAM_9X16": "9x16",
                "OUTROS_REVISAR": "outros",
                "FOTOS": "foto",
            }
            parts = [
                (asset.capture_date or "sem-data")[:10],
                group.name_final[:48],
                *(
                    [asset.movement[:24]]
                    if asset.movement and asset.movement.casefold() != "desconhecido"
                    else []
                ),
                *(
                    [asset.people[:24]]
                    if asset.people and asset.people.casefold() != "desconhecido"
                    else []
                ),
                formats[asset.classification],
                asset.asset_id[:8],
            ]
            extension = PurePosixPath(original.rel_path).suffix.lower()
            return safe_filename(f"{'_'.join(parts)}{extension}", asset.asset_id)
    name = safe_filename(PurePosixPath(original.rel_path).name, asset.asset_id)
    names = session.execute(
        select(CatalogAsset.asset_id, AssetFile.rel_path)
        .join(AssetFile, AssetFile.catalog_asset_id == CatalogAsset.id)
        .where(CatalogAsset.trip_id == asset.trip_id, AssetFile.role == "ORIGINAL")
    ).all()
    duplicates = sum(
        safe_filename(PurePosixPath(rel_path).name, asset_id).casefold()
        == name.casefold()
        for asset_id, rel_path in names
    )
    if duplicates > 1:
        stem, extension = os.path.splitext(name)
        return f"{stem}-{asset.asset_id[:12]}{extension}"
    return name


def resolve_original(
    session: Session, settings: ServerSettings, asset: CatalogAsset
) -> OriginalDownload:
    """Resolve only a registered AVAILABLE ORIGINAL under the configured OMV root."""
    original = session.scalar(
        select(AssetFile).where(
            AssetFile.catalog_asset_id == asset.id,
            AssetFile.role == "ORIGINAL",
        )
    )
    trip_slug = session.scalar(select(Trip.slug).where(Trip.id == asset.trip_id))
    if original is None or original.availability_status != "AVAILABLE" or not trip_slug:
        raise _unavailable()
    rel = original.rel_path
    parts = PurePosixPath(rel).parts
    allowed_suffixes = {".mp4"} if asset.media_type == "VIDEO" else {".jpg", ".jpeg"}
    if (
        not parts
        or parts[0] != trip_slug
        or PurePosixPath(rel).suffix.lower() not in allowed_suffixes
    ):
        raise _unavailable()
    try:
        path = resolve_omv_path(settings.omv_root, rel)
        if not path.is_file():
            raise _unavailable()
        size = path.stat().st_size
        if size <= 0 or (
            original.size_bytes is not None and size != original.size_bytes
        ):
            raise _unavailable()
    except (ManifestError, OSError) as error:
        raise _unavailable() from error
    return OriginalDownload(
        path=path,
        filename=_editorial_name(session, asset, original),
        size_bytes=size,
        media_type="video/mp4" if asset.media_type == "VIDEO" else "image/jpeg",
    )
