"""Per-user persistent selections for editorial catalog assets."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from drone_media_manager.db.models.auth import AssetSelection
from drone_media_manager.db.models.catalog import CatalogAsset
from drone_media_manager.time import utc_now


def is_selected(session: Session, user_id: str, catalog_asset_id: str) -> bool:
    return (
        session.scalar(
            select(AssetSelection.id).where(
                AssetSelection.user_id == user_id,
                AssetSelection.catalog_asset_id == catalog_asset_id,
            )
        )
        is not None
    )


def selected_count(session: Session, user_id: str, trip_id: str) -> int:
    return int(
        session.scalar(
            select(func.count(AssetSelection.id))
            .join(CatalogAsset, AssetSelection.catalog_asset_id == CatalogAsset.id)
            .where(AssetSelection.user_id == user_id, CatalogAsset.trip_id == trip_id)
        )
        or 0
    )


def set_selected(
    session: Session, user_id: str, catalog_asset_id: str, selected: bool
) -> None:
    if selected:
        statement = sqlite_insert(AssetSelection).values(
            id=str(uuid4()),
            user_id=user_id,
            catalog_asset_id=catalog_asset_id,
            updated_at=utc_now(),
        )
        session.execute(
            statement.on_conflict_do_nothing(
                index_elements=["user_id", "catalog_asset_id"]
            )
        )
    else:
        session.execute(
            delete(AssetSelection).where(
                AssetSelection.user_id == user_id,
                AssetSelection.catalog_asset_id == catalog_asset_id,
            )
        )
    session.commit()


def set_selected_many(
    session: Session, user_id: str, catalog_asset_ids: list[str], selected: bool
) -> None:
    if selected:
        session.execute(
            sqlite_insert(AssetSelection)
            .values(
                [
                    {
                        "id": str(uuid4()),
                        "user_id": user_id,
                        "catalog_asset_id": asset_id,
                        "updated_at": utc_now(),
                    }
                    for asset_id in catalog_asset_ids
                ]
            )
            .on_conflict_do_nothing(index_elements=["user_id", "catalog_asset_id"])
        )
    else:
        session.execute(
            delete(AssetSelection).where(
                AssetSelection.user_id == user_id,
                AssetSelection.catalog_asset_id.in_(catalog_asset_ids),
            )
        )
    session.commit()
