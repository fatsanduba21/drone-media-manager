"""Read-only editorial catalog and bounded derivative media delivery."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from drone_media_manager.api.auth import require_browser_identity
from drone_media_manager.catalog.importer import ManifestError, resolve_omv_path
from drone_media_manager.catalog.selection import is_selected
from drone_media_manager.config import ServerSettings
from drone_media_manager.db.models.catalog import CatalogAsset, Derivative
from drone_media_manager.db.models.ingest import Trip
from drone_media_manager.derivatives.service import PROFILES
from drone_media_manager.grouping.repository import ordered_assets

_CACHE = "private, max-age=3600, must-revalidate"
_RANGE = re.compile(r"bytes=(\d*)-(\d*)\Z")


def _missing(code: str) -> HTTPException:
    return HTTPException(status_code=404, detail={"code": code})


def _trip(session: Session, slug: str) -> Trip:
    trip = session.scalar(select(Trip).where(Trip.slug == slug))
    if trip is None:
        raise _missing("trip_not_found")
    return trip


def _trip_payload(session: Session, trip: Trip) -> dict[str, object]:
    count = session.scalar(
        select(func.count(CatalogAsset.id)).where(CatalogAsset.trip_id == trip.id)
    )
    return {"slug": trip.slug, "name": trip.name, "asset_count": count or 0}


def _matches(value: str | None, expected: str | None) -> bool:
    return not expected or (
        value is not None and value.casefold() == expected.casefold()
    )


def _assets(
    session: Session,
    trip: Trip,
    *,
    classification: str | None = None,
    poi: str | None = None,
    movement: str | None = None,
    people: str | None = None,
    media_type: str | None = None,
) -> list[CatalogAsset]:
    candidates = ordered_assets(session, trip.id, include_missing=True)
    return [
        asset
        for asset in candidates
        if (not classification or asset.classification == classification.upper())
        and (not media_type or asset.media_type == media_type.upper())
        and _matches(asset.poi_final or asset.poi_suggested, poi)
        and _matches(asset.movement, movement)
        and _matches(asset.people, people)
    ]


def _asset(session: Session, asset_id: str) -> CatalogAsset:
    asset = session.scalar(
        select(CatalogAsset).where(CatalogAsset.asset_id == asset_id)
    )
    if asset is None:
        raise _missing("asset_not_found")
    return asset


def _asset_payload(
    session: Session,
    asset: CatalogAsset,
    settings: ServerSettings,
    user_id: str | None = None,
) -> dict[str, object]:
    ready: set[str] = set()
    kinds = ("THUMBNAIL", "PROXY") if asset.media_type == "VIDEO" else ("THUMBNAIL",)
    for kind in kinds:
        try:
            _ready_path(session, settings, asset, kind)
        except HTTPException:
            continue
        ready.add(kind)
    base = f"/api/catalog/assets/{asset.asset_id}"
    trip_slug = session.scalar(select(Trip.slug).where(Trip.id == asset.trip_id))
    return {
        "asset_id": asset.asset_id,
        "trip_slug": trip_slug,
        "media_type": asset.media_type,
        "classification": asset.classification,
        "duration_ms": asset.duration_ms,
        "poi": asset.poi_final or asset.poi_suggested,
        "movement": asset.movement,
        "people": asset.people,
        "display_width": asset.display_width,
        "display_height": asset.display_height,
        "rotation_degrees": asset.rotation_degrees,
        "capture_date": asset.capture_date,
        "verification_status": asset.verification_status,
        "selected": is_selected(session, user_id, asset.id) if user_id else False,
        "thumbnail_url": f"{base}/thumbnail" if "THUMBNAIL" in ready else None,
        "proxy_url": (
            f"{base}/proxy"
            if asset.media_type == "VIDEO" and "PROXY" in ready
            else None
        ),
    }


def _ready_path(
    session: Session, settings: ServerSettings, asset: CatalogAsset, kind: str
) -> tuple[Path, Derivative]:
    if kind == "PROXY" and asset.media_type != "VIDEO":
        raise _missing("derivative_not_found")
    derivative = session.scalar(
        select(Derivative).where(
            Derivative.catalog_asset_id == asset.id,
            Derivative.kind == kind,
            Derivative.status == "READY",
        )
    )
    if (
        derivative is None
        or derivative.rel_path is None
        or derivative.output_sha256 is None
        or derivative.size_bytes is None
        or derivative.size_bytes <= 0
        or derivative.profile_version != PROFILES[kind]
    ):
        raise _missing("derivative_not_found")
    suffix = ".jpg" if kind == "THUMBNAIL" else ".mp4"
    expected = (
        f"{asset.asset_id[:2]}/{asset.asset_id}/{derivative.profile_version}{suffix}"
    )
    if derivative.rel_path != expected:
        raise _missing("derivative_not_found")
    assert settings.derivatives_root is not None
    try:
        path = resolve_omv_path(settings.derivatives_root, derivative.rel_path)
        if not path.is_file() or path.stat().st_size != derivative.size_bytes:
            raise _missing("derivative_not_found")
    except (ManifestError, OSError) as error:
        raise _missing("derivative_not_found") from error
    return path, derivative


def _byte_range(value: str, size: int) -> tuple[int, int] | None:
    match = _RANGE.fullmatch(value)
    if match is None or (not match[1] and not match[2]):
        return None
    if len(match[1]) > 20 or len(match[2]) > 20:
        return None
    if match[1]:
        start = int(match[1])
        end = min(int(match[2]), size - 1) if match[2] else size - 1
        if start >= size or end < start:
            return None
        return start, end
    suffix = int(match[2])
    if suffix == 0:
        return None
    return max(size - suffix, 0), size - 1


def catalog_router(
    settings: ServerSettings, session_factory: Callable[[], Session]
) -> APIRouter:
    router = APIRouter(prefix="/api/catalog")

    @router.get("/trips")
    def trips() -> dict[str, object]:
        with session_factory() as session:
            rows = session.execute(
                select(Trip, func.count(CatalogAsset.id))
                .join(CatalogAsset, CatalogAsset.trip_id == Trip.id)
                .group_by(Trip.id)
                .order_by(Trip.name, Trip.slug)
            ).all()
            return {
                "trips": [
                    {"slug": trip.slug, "name": trip.name, "asset_count": count}
                    for trip, count in rows
                ]
            }

    @router.get("/trips/{slug}")
    def trip_detail(slug: str) -> dict[str, object]:
        with session_factory() as session:
            return _trip_payload(session, _trip(session, slug))

    @router.get("/trips/{slug}/assets")
    def trip_assets(
        slug: str,
        request: Request,
        classification: str | None = None,
        poi: str | None = None,
        movement: str | None = None,
        people: str | None = None,
        media_type: str | None = None,
    ) -> dict[str, object]:
        with session_factory() as session:
            trip = _trip(session, slug)
            assets = _assets(
                session,
                trip,
                classification=classification,
                poi=poi,
                movement=movement,
                people=people,
                media_type=media_type,
            )
            return {
                "trip": _trip_payload(session, trip),
                "total": len(assets),
                "assets": [
                    _asset_payload(
                        session,
                        asset,
                        settings,
                        require_browser_identity(request).user_id,
                    )
                    for asset in assets
                ],
            }

    @router.get("/assets/{asset_id}")
    def asset_detail(asset_id: str, request: Request) -> dict[str, object]:
        with session_factory() as session:
            return _asset_payload(
                session,
                _asset(session, asset_id),
                settings,
                require_browser_identity(request).user_id,
            )

    @router.get("/assets/{asset_id}/thumbnail", response_model=None)
    def thumbnail(asset_id: str, request: Request) -> Response:
        with session_factory() as session:
            path, derivative = _ready_path(
                session, settings, _asset(session, asset_id), "THUMBNAIL"
            )
        etag = f'"{derivative.output_sha256}"'
        headers = {"Cache-Control": _CACHE, "ETag": etag}
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers=headers)
        return FileResponse(path, media_type="image/jpeg", headers=headers)

    @router.get("/assets/{asset_id}/proxy", response_model=None)
    def proxy(asset_id: str, request: Request) -> Response:
        with session_factory() as session:
            path, derivative = _ready_path(
                session, settings, _asset(session, asset_id), "PROXY"
            )
        size = derivative.size_bytes
        assert size is not None
        etag = f'"{derivative.output_sha256}"'
        headers = {"Accept-Ranges": "bytes", "ETag": etag, "Cache-Control": _CACHE}
        range_value = request.headers.get("range")
        if range_value and _byte_range(range_value, size) is None:
            headers["Content-Range"] = f"bytes */{size}"
            return Response(status_code=416, headers=headers)
        return FileResponse(path, media_type="video/mp4", headers=headers)

    return router
