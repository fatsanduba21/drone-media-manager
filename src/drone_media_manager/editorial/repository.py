"""Transactional human edits to catalog classifications."""

from __future__ import annotations

import json
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from drone_media_manager.db.models.catalog import CatalogAsset
from drone_media_manager.db.models.core import AuditEvent
from drone_media_manager.editorial.models import EditorialField, EditorialTag
from drone_media_manager.grouping.models import LocationGroup
from drone_media_manager.movement.repository import review_movement
from drone_media_manager.time import utc_now


def _clean_text(value: str, limit: int) -> str:
    cleaned = " ".join(value.split())
    if not cleaned or len(cleaned) > limit or any(ord(char) < 32 for char in value):
        raise ValueError("invalid_editorial_text")
    return cleaned


def update_assets(
    session: Session,
    trip_id: str,
    asset_ids: list[str],
    *,
    actor: str,
    group_id: str | None = None,
    movement: str | None = None,
    people: str | None = None,
    subject: str | None = None,
    people_label: str | None = None,
    add_tags: list[str] | None = None,
    remove_tags: list[str] | None = None,
) -> int:
    """Apply only supplied fields; omitted fields are never overwritten."""
    if not asset_ids or len(asset_ids) > 200 or len(set(asset_ids)) != len(asset_ids):
        raise ValueError("invalid_asset_selection")
    assets = session.scalars(
        select(CatalogAsset).where(CatalogAsset.id.in_(asset_ids))
    ).all()
    if len(assets) != len(asset_ids) or any(
        asset.trip_id != trip_id for asset in assets
    ):
        raise ValueError("asset_not_in_trip")
    if group_id is not None:
        group = session.get(LocationGroup, group_id)
        if group is None or group.trip_id != trip_id:
            raise ValueError("group_not_in_trip")
    if people is not None and people not in {"YES", "NO", "UNKNOWN"}:
        raise ValueError("invalid_people")
    fields = {
        "PEOPLE": people,
        "SUBJECT": _clean_text(subject, 255) if subject is not None else None,
        "PEOPLE_LABEL": _clean_text(people_label, 255)
        if people_label is not None
        else None,
    }
    additions = {_clean_text(tag, 64).casefold() for tag in (add_tags or [])}
    removals = {_clean_text(tag, 64).casefold() for tag in (remove_tags or [])}
    if additions & removals:
        raise ValueError("conflicting_tags")
    if not any(
        (group_id, movement, people, subject, people_label, additions, removals)
    ):
        raise ValueError("no_changes")
    existing_fields = {
        (row.catalog_asset_id, row.kind): row
        for row in session.scalars(
            select(EditorialField).where(EditorialField.catalog_asset_id.in_(asset_ids))
        )
    }
    existing_tags: dict[str, dict[str, EditorialTag]] = {}
    for row in session.scalars(
        select(EditorialTag).where(EditorialTag.catalog_asset_id.in_(asset_ids))
    ):
        existing_tags.setdefault(row.catalog_asset_id, {})[row.value] = row
    for asset in assets:
        if group_id is not None:
            asset.location_group_id = group_id
        if movement is not None:
            review_movement(session, asset.id, movement, actor=actor)
        for kind, value in fields.items():
            if value is None:
                continue
            field_row = existing_fields.get((asset.id, kind))
            if field_row is None:
                field_row = EditorialField(
                    catalog_asset_id=asset.id, kind=kind, value=value, actor=actor
                )
                session.add(field_row)
            else:
                field_row.value, field_row.actor, field_row.updated_at = (
                    value,
                    actor,
                    utc_now(),
                )
            if kind == "PEOPLE":
                asset.people = value
        tags = existing_tags.get(asset.id, {})
        for tag in removals:
            if tag in tags:
                session.delete(tags[tag])
        for tag in additions - tags.keys():
            session.add(EditorialTag(catalog_asset_id=asset.id, value=tag, actor=actor))
        session.add(
            AuditEvent(
                actor=actor,
                action="editorial.update",
                entity_type="catalog_asset",
                entity_id=asset.id,
                result="accepted",
                correlation_id=str(uuid4()),
                details_json=json.dumps(
                    {
                        "group_id": group_id,
                        "movement": movement,
                        "fields": {k: v for k, v in fields.items() if v is not None},
                        "add_tags": sorted(additions),
                        "remove_tags": sorted(removals),
                    },
                    ensure_ascii=False,
                ),
            )
        )
    session.flush()
    return len(assets)
