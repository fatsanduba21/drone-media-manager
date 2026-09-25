"""Authenticated editorial review and optional place naming routes."""

from __future__ import annotations

import json
from collections.abc import Callable
from html import escape
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from drone_media_manager.api.auth import (
    BrowserIdentity,
    require_browser_identity,
    require_csrf,
)
from drone_media_manager.catalog.importer import resolve_omv_path
from drone_media_manager.config import ServerSettings
from drone_media_manager.db.models.catalog import AssetFile, CatalogAsset, Derivative
from drone_media_manager.db.models.ingest import Trip
from drone_media_manager.grouping.models import GroupingSuggestion, LocationGroup
from drone_media_manager.grouping.names import GooglePlacesProvider, NameLookup
from drone_media_manager.grouping.repository import (
    analyze_trip,
    assign_range,
    ordered_assets,
    range_center,
    rename_group,
)
from drone_media_manager.movement.models import MovementAnalysis


class RangeRequest(BaseModel):
    start_asset_id: str
    end_asset_id: str
    name: str | None = Field(default=None, max_length=255)
    place_id: str | None = Field(default=None, max_length=512)


class GroupUpdateRequest(RangeRequest):
    mode: Literal["add", "replace"] = "replace"


class GroupNameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)


def _group_data(group: LocationGroup) -> dict[str, object]:
    return {
        "id": group.id,
        "name": group.name_final,
        "name_source": group.name_source,
        "place_id": group.provider_place_id,
    }


def editorial_router(
    settings: ServerSettings, sessions: Callable[[], Session]
) -> APIRouter:
    router = APIRouter()
    api_key = settings.google_maps_api_key
    lookup = NameLookup(
        GooglePlacesProvider(api_key.get_secret_value())
        if api_key is not None and api_key.get_secret_value().strip()
        else None
    )

    def admin(request: Request, *, write: bool = False) -> BrowserIdentity:
        if write:
            return require_csrf(request, request.headers.get("x-csrf-token"))
        return require_browser_identity(request)

    @router.get("/editorial/", response_class=HTMLResponse)
    def gallery(request: Request) -> HTMLResponse:
        identity = admin(request)
        html = Path(__file__).resolve().parents[1] / "static" / "editorial.html"
        page = html.read_text(encoding="utf-8").replace(
            "__DMM_CSRF_TOKEN__", escape(identity.csrf_token, quote=True)
        )
        return HTMLResponse(page, headers={"Cache-Control": "no-store"})

    @router.get("/api/editorial/trips")
    def trips(request: Request) -> list[dict[str, object]]:
        admin(request)
        with sessions() as session:
            rows = session.execute(
                select(Trip.id, Trip.name, func.count(CatalogAsset.id))
                .join(CatalogAsset, CatalogAsset.trip_id == Trip.id)
                .group_by(Trip.id, Trip.name)
                .order_by(Trip.name)
            ).all()
            return [
                {"id": trip_id, "name": name, "asset_count": count}
                for trip_id, name, count in rows
            ]

    @router.get("/api/editorial/trips/{trip_id}")
    def trip_state(trip_id: str, request: Request) -> dict[str, object]:
        admin(request)
        with sessions() as session:
            trip = session.get(Trip, trip_id)
            if trip is None:
                raise HTTPException(404, detail={"code": "trip_not_found"})
            assets = ordered_assets(session, trip_id)
            ids = [asset.id for asset in assets]
            movements = {
                row.catalog_asset_id: row
                for row in session.scalars(
                    select(MovementAnalysis).where(
                        MovementAnalysis.catalog_asset_id.in_(ids),
                        MovementAnalysis.superseded_at.is_(None),
                    )
                )
            }
            originals = (
                {
                    row.catalog_asset_id: row
                    for row in session.scalars(
                        select(AssetFile).where(
                            AssetFile.catalog_asset_id.in_(ids),
                            AssetFile.role == "ORIGINAL",
                        )
                    )
                }
                if ids
                else {}
            )
            thumbnails = (
                {
                    row.catalog_asset_id: row
                    for row in session.scalars(
                        select(Derivative).where(
                            Derivative.catalog_asset_id.in_(ids),
                            Derivative.kind == "THUMBNAIL",
                        )
                    )
                }
                if ids
                else {}
            )
            groups = session.scalars(
                select(LocationGroup)
                .where(LocationGroup.trip_id == trip_id)
                .order_by(LocationGroup.created_at)
            ).all()
            suggestions = session.scalars(
                select(GroupingSuggestion)
                .where(
                    GroupingSuggestion.trip_id == trip_id,
                    GroupingSuggestion.superseded_at.is_(None),
                )
                .order_by(GroupingSuggestion.created_at, GroupingSuggestion.id)
            ).all()
            return {
                "trip": {"id": trip.id, "name": trip.name, "slug": trip.slug},
                "assets": [
                    {
                        "id": asset.id,
                        "asset_id": asset.asset_id,
                        "filename": Path(originals[asset.id].rel_path).name,
                        "media_type": asset.media_type,
                        "location_group_id": asset.location_group_id,
                        "movement_final": asset.movement,
                        "movement_suggested": movements[asset.id].value
                        if asset.id in movements
                        else None,
                        "thumbnail_url": (
                            f"/api/editorial/assets/{asset.id}/thumbnail"
                            if asset.id in thumbnails
                            and thumbnails[asset.id].status == "READY"
                            and thumbnails[asset.id].source_sha256
                            == originals[asset.id].sha256
                            else None
                        ),
                    }
                    for asset in assets
                ],
                "groups": [_group_data(group) for group in groups],
                "suggestions": [
                    {
                        "id": suggestion.id,
                        "start_asset_id": suggestion.start_asset_id,
                        "end_asset_id": suggestion.end_asset_id,
                        "confidence": suggestion.confidence,
                        "algorithm_version": suggestion.algorithm_version,
                        "evidence": json.loads(suggestion.evidence_json),
                    }
                    for suggestion in suggestions
                ],
            }

    @router.get("/api/editorial/assets/{asset_id}/thumbnail")
    def thumbnail(asset_id: str, request: Request) -> FileResponse:
        admin(request)
        with sessions() as session:
            asset = session.get(CatalogAsset, asset_id)
            original = session.scalar(
                select(AssetFile).where(
                    AssetFile.catalog_asset_id == asset_id, AssetFile.role == "ORIGINAL"
                )
            )
            derivative = session.scalar(
                select(Derivative).where(
                    Derivative.catalog_asset_id == asset_id,
                    Derivative.kind == "THUMBNAIL",
                )
            )
            if (
                asset is None
                or original is None
                or derivative is None
                or derivative.status != "READY"
                or derivative.rel_path is None
                or derivative.source_sha256 != original.sha256
            ):
                raise HTTPException(404, detail={"code": "thumbnail_not_found"})
            assert settings.derivatives_root is not None
            try:
                path = resolve_omv_path(settings.derivatives_root, derivative.rel_path)
            except ValueError:
                raise HTTPException(
                    404, detail={"code": "thumbnail_not_found"}
                ) from None
            if not path.is_file():
                raise HTTPException(404, detail={"code": "thumbnail_not_found"})
            return FileResponse(path, media_type="image/jpeg")

    @router.post("/api/editorial/trips/{trip_id}/analyze")
    def analyze(trip_id: str, request: Request) -> dict[str, int]:
        admin(request, write=True)
        with sessions() as session, session.begin():
            if session.get(Trip, trip_id) is None:
                raise HTTPException(404, detail={"code": "trip_not_found"})
            suggestions = analyze_trip(session, settings, trip_id)
            return {"suggestion_count": len(suggestions)}

    @router.get("/api/editorial/trips/{trip_id}/name-suggestions")
    def name_suggestions(
        trip_id: str,
        request: Request,
        start_asset_id: str,
        end_asset_id: str,
    ) -> dict[str, object]:
        admin(request)
        with sessions() as session:
            if session.get(Trip, trip_id) is None:
                raise HTTPException(404, detail={"code": "trip_not_found"})
            try:
                center = range_center(session, trip_id, start_asset_id, end_asset_id)
            except ValueError as error:
                raise HTTPException(422, detail={"code": str(error)}) from error
        if center is None or lookup.provider is None:
            return {"candidates": [], "source": "manual"}
        candidates = lookup.suggest_names(*center, 500)
        return {
            "candidates": [
                {"name": candidate.name, "place_id": candidate.place_id}
                for candidate in candidates
            ],
            "source": "google_places" if candidates else "manual",
        }

    @router.post("/api/editorial/trips/{trip_id}/groups", status_code=201)
    def create_group(
        trip_id: str, payload: RangeRequest, request: Request
    ) -> dict[str, object]:
        identity = admin(request, write=True)
        with sessions() as session, session.begin():
            if session.get(Trip, trip_id) is None:
                raise HTTPException(404, detail={"code": "trip_not_found"})
            try:
                group = assign_range(
                    session,
                    trip_id,
                    payload.start_asset_id,
                    payload.end_asset_id,
                    name=payload.name,
                    place_id=payload.place_id,
                    actor=identity.user_id,
                )
            except ValueError as error:
                raise HTTPException(422, detail={"code": str(error)}) from error
            return _group_data(group)

    @router.put("/api/editorial/trips/{trip_id}/groups/{group_id}")
    def update_group(
        trip_id: str, group_id: str, payload: GroupUpdateRequest, request: Request
    ) -> dict[str, object]:
        identity = admin(request, write=True)
        with sessions() as session, session.begin():
            try:
                group = assign_range(
                    session,
                    trip_id,
                    payload.start_asset_id,
                    payload.end_asset_id,
                    name=payload.name,
                    place_id=payload.place_id,
                    group_id=group_id,
                    replace_existing=payload.mode == "replace",
                    actor=identity.user_id,
                )
            except ValueError as error:
                raise HTTPException(422, detail={"code": str(error)}) from error
            return _group_data(group)

    @router.patch("/api/editorial/trips/{trip_id}/groups/{group_id}/name")
    def edit_group_name(
        trip_id: str, group_id: str, payload: GroupNameRequest, request: Request
    ) -> dict[str, object]:
        identity = admin(request, write=True)
        with sessions() as session, session.begin():
            try:
                group = rename_group(
                    session, trip_id, group_id, payload.name, actor=identity.user_id
                )
            except ValueError as error:
                raise HTTPException(422, detail={"code": str(error)}) from error
            return _group_data(group)

    return router
