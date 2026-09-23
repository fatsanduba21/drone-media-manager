"""Authenticated individual originals and batch preflight without archive creation."""

from __future__ import annotations

import os
import unicodedata
from collections.abc import Callable
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from drone_media_manager.api.auth import require_browser_identity
from drone_media_manager.api.routes.catalog import _asset, _trip
from drone_media_manager.catalog.downloads import OriginalDownload, resolve_original
from drone_media_manager.config import ServerSettings
from drone_media_manager.db.models.auth import AssetSelection
from drone_media_manager.db.models.catalog import CatalogAsset


def _content_disposition(filename: str) -> str:
    stem, extension = os.path.splitext(filename)
    ascii_stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode()
    ascii_stem = "".join(
        char if char.isalnum() or char in " ._-" else "_" for char in ascii_stem
    ).strip(" .")
    ascii_extension = "".join(
        char if char.isascii() and (char.isalnum() or char == ".") else "_"
        for char in extension
    )[:16]
    fallback = f"{ascii_stem or 'original'}{ascii_extension}"
    return (
        f'attachment; filename="{fallback}"; '
        f"filename*=UTF-8''{quote(filename, safe='')}"
    )


def _file_response(original: OriginalDownload) -> FileResponse:
    return FileResponse(
        original.path,
        media_type=original.media_type,
        headers={
            "Content-Disposition": _content_disposition(original.filename),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


def selected_originals(
    session: Session, settings: ServerSettings, user_id: str, trip_id: str
) -> list[tuple[CatalogAsset, OriginalDownload]]:
    assets = session.scalars(
        select(CatalogAsset)
        .join(AssetSelection, AssetSelection.catalog_asset_id == CatalogAsset.id)
        .where(AssetSelection.user_id == user_id, CatalogAsset.trip_id == trip_id)
        .order_by(CatalogAsset.asset_id)
    ).all()
    if not assets:
        raise HTTPException(status_code=409, detail={"code": "selection_empty"})
    return [(asset, resolve_original(session, settings, asset)) for asset in assets]


def downloads_router(
    settings: ServerSettings, session_factory: Callable[[], Session]
) -> APIRouter:
    router = APIRouter(prefix="/api/catalog")

    @router.get("/assets/{asset_id}/download", response_model=None)
    def individual(asset_id: str, request: Request) -> FileResponse:
        require_browser_identity(request)
        with session_factory() as session:
            original = resolve_original(session, settings, _asset(session, asset_id))
        return _file_response(original)

    @router.get("/trips/{slug}/selected-downloads")
    def selected(slug: str, request: Request) -> dict[str, object]:
        identity = require_browser_identity(request)
        with session_factory() as session:
            trip = _trip(session, slug)
            originals = selected_originals(session, settings, identity.user_id, trip.id)
            files = [
                {
                    "asset_id": asset.asset_id,
                    "filename": original.filename,
                    "size_bytes": original.size_bytes,
                    "url": f"/api/catalog/assets/{quote(asset.asset_id, safe='')}/download",
                }
                for asset, original in originals
            ]
        return {
            "count": len(files),
            "total_size_bytes": sum(
                item["size_bytes"]
                for item in files
                if isinstance(item["size_bytes"], int)
            ),
            "files": files,
        }

    return router
