"""Authenticated, CSRF-protected persistent catalog selection routes."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from drone_media_manager.api.auth import _form_fields, require_csrf
from drone_media_manager.api.routes.catalog import _asset, _trip
from drone_media_manager.catalog.selection import (
    selected_count,
    set_selected,
    set_selected_many,
)
from drone_media_manager.db.models.catalog import CatalogAsset


class SelectionChange(BaseModel):
    selected: bool


class BulkSelectionChange(BaseModel):
    asset_ids: list[str] = Field(min_length=1, max_length=2000)
    selected: bool


def selection_router(session_factory: Callable[[], Session]) -> APIRouter:
    router = APIRouter()

    @router.put("/api/catalog/trips/{slug}/selection")
    def api_bulk_selection(
        slug: str, change: BulkSelectionChange, request: Request
    ) -> dict[str, int]:
        identity = require_csrf(request, request.headers.get("x-csrf-token"))
        if len(change.asset_ids) != len(set(change.asset_ids)):
            raise HTTPException(status_code=422, detail={"code": "duplicate_asset_id"})
        with session_factory() as session:
            trip = _trip(session, slug)
            assets = session.execute(
                select(CatalogAsset.id, CatalogAsset.asset_id).where(
                    CatalogAsset.trip_id == trip.id,
                    CatalogAsset.asset_id.in_(change.asset_ids),
                )
            ).all()
            if len(assets) != len(change.asset_ids):
                raise HTTPException(status_code=404, detail={"code": "asset_not_found"})
            set_selected_many(
                session,
                identity.user_id,
                [asset_id for asset_id, _ in assets],
                change.selected,
            )
            return {
                "selected_count": selected_count(session, identity.user_id, trip.id)
            }

    @router.put("/api/catalog/assets/{asset_id}/selection")
    def api_selection(
        asset_id: str, change: SelectionChange, request: Request
    ) -> dict[str, object]:
        identity = require_csrf(request, request.headers.get("x-csrf-token"))
        with session_factory() as session:
            asset = _asset(session, asset_id)
            set_selected(session, identity.user_id, asset.id, change.selected)
            return {
                "asset_id": asset.asset_id,
                "selected": change.selected,
                "selected_count": selected_count(
                    session, identity.user_id, asset.trip_id
                ),
            }

    @router.post("/gallery/{slug}/assets/{asset_id}/selection", response_model=None)
    async def gallery_selection(
        slug: str, asset_id: str, request: Request
    ) -> RedirectResponse:
        fields = await _form_fields(request)
        identity = require_csrf(request, fields.get("csrf_token"))
        value = fields.get("selected")
        if value not in {"true", "false"}:
            raise HTTPException(status_code=422, detail={"code": "invalid_selection"})
        with session_factory() as session:
            trip = _trip(session, slug)
            asset = _asset(session, asset_id)
            if asset.trip_id != trip.id:
                raise HTTPException(status_code=404, detail={"code": "asset_not_found"})
            set_selected(session, identity.user_id, asset.id, value == "true")
        destination = (
            f"/gallery/{slug}/assets/{asset_id}"
            if fields.get("next") == "detail"
            else f"/gallery/{slug}"
        )
        return RedirectResponse(destination, status_code=303)

    return router
