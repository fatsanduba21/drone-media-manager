"""Transactions for confirmed ingest state and optimistic progress checkpoints."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from drone_media_manager.db.models.ingest import (
    IngestItem,
    IngestJob,
    MediaFile,
    SourceSnapshot,
    SourceSnapshotEntry,
)
from drone_media_manager.domain.enums import IngestStatus, SourceKind
from drone_media_manager.domain.errors import InvalidTransition, StaleRevision
from drone_media_manager.time import utc_now

_INGEST_EDGES: dict[IngestStatus, frozenset[IngestStatus]] = {
    IngestStatus.DISCOVERED: frozenset(
        {IngestStatus.COPYING, IngestStatus.INTERRUPTED, IngestStatus.FAILED}
    ),
    IngestStatus.COPYING: frozenset(
        {IngestStatus.VERIFYING, IngestStatus.INTERRUPTED, IngestStatus.FAILED}
    ),
    IngestStatus.VERIFYING: frozenset(
        {IngestStatus.VERIFIED, IngestStatus.INTERRUPTED, IngestStatus.FAILED}
    ),
    IngestStatus.INTERRUPTED: frozenset(),
    IngestStatus.FAILED: frozenset(),
    IngestStatus.VERIFIED: frozenset(),
}


class IngestRepository:
    """Own short SQLite transactions for ingest state only."""

    def __init__(self, session: Session) -> None:
        self.session = session

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        if self.session.in_transaction():
            raise RuntimeError("IngestRepository requires an idle session")
        with self.session.begin():
            self.session.execute(text("BEGIN IMMEDIATE"))
            yield

    def create_snapshot(
        self,
        *,
        worker_id: str,
        source_kind: SourceKind,
        source_volume_identity: str | None,
        expires_at: datetime,
        entries: Iterable[SourceSnapshotEntry] = (),
    ) -> SourceSnapshot:
        """Persist a draft source snapshot with relative entries only."""

        with self._transaction():
            snapshot = SourceSnapshot(
                worker_id=worker_id,
                source_kind=source_kind,
                source_volume_identity=source_volume_identity,
                expires_at=_utc(expires_at),
            )
            self.session.add(snapshot)
            self.session.flush()
            for entry in entries:
                entry.snapshot_id = snapshot.id
                self.session.add(entry)
            self.session.flush()
        return snapshot

    def confirm_ingest(
        self,
        *,
        trip_id: str,
        source_kind: SourceKind,
        source_fingerprint: str,
        source_volume_identity: str | None = None,
        snapshot_id: str | None = None,
    ) -> IngestJob:
        """Create or reuse the idempotent ingest aggregate for a trip/fingerprint."""

        with self._transaction():
            existing = self.session.scalar(
                select(IngestJob).where(
                    IngestJob.trip_id == trip_id,
                    IngestJob.source_fingerprint == source_fingerprint,
                )
            )
            if existing is not None:
                return existing
            ingest = IngestJob(
                trip_id=trip_id,
                source_snapshot_id=snapshot_id,
                source_kind=source_kind,
                source_volume_identity=source_volume_identity,
                source_fingerprint=source_fingerprint,
            )
            self.session.add(ingest)
            self.session.flush()
        return ingest

    def transition_ingest(
        self,
        ingest_id: str,
        *,
        expected_revision: int,
        target: IngestStatus,
    ) -> IngestJob:
        """Advance one legal ingest edge with an optimistic revision check."""

        with self._transaction():
            ingest = self._ingest_with_revision(ingest_id, expected_revision)
            current = IngestStatus(ingest.status)
            if target not in _INGEST_EDGES[current]:
                raise InvalidTransition(
                    f"Cannot transition ingest from {current} to {target}"
                )
            ingest.status = target
            ingest.revision += 1
            ingest.updated_at = utc_now()
            self.session.flush()
        return ingest

    def checkpoint_item(
        self,
        item_id: str,
        *,
        expected_revision: int,
        bytes_copied: int,
        source_sha256: str | None = None,
    ) -> IngestItem:
        """Durably record progress only for the expected item revision."""

        if bytes_copied < 0:
            raise ValueError("bytes_copied must be non-negative")
        with self._transaction():
            item = self.session.get(IngestItem, item_id, populate_existing=True)
            if item is None or item.revision != expected_revision:
                raise StaleRevision("ingest item revision is stale")
            if (
                bytes_copied < item.bytes_copied
                or bytes_copied > item.source_size_bytes
            ):
                raise ValueError(
                    "bytes_copied must advance without exceeding source size"
                )
            item.bytes_copied = bytes_copied
            item.source_sha256 = source_sha256 or item.source_sha256
            item.revision += 1
            item.updated_at = utc_now()
            self.session.flush()
        return item

    def record_verified_media(
        self,
        item_id: str,
        *,
        expected_revision: int,
        media_type: str,
        sha256: str,
    ) -> MediaFile:
        """Persist the deduplicated media identity after an item is verified."""

        with self._transaction():
            item = self.session.get(IngestItem, item_id, populate_existing=True)
            if item is None or item.revision != expected_revision:
                raise StaleRevision("ingest item revision is stale")
            ingest = self.session.get(IngestJob, item.ingest_job_id)
            if ingest is None:
                raise ValueError("ingest item has no aggregate ingest")
            existing = self.session.scalar(
                select(MediaFile).where(
                    MediaFile.trip_id == ingest.trip_id,
                    MediaFile.media_type == media_type,
                    MediaFile.size_bytes == item.source_size_bytes,
                    MediaFile.sha256 == sha256,
                )
            )
            if existing is not None:
                return existing
            media = MediaFile(
                trip_id=ingest.trip_id,
                ingest_item_id=item.id,
                original_filename=item.source_rel_path.rsplit("/", maxsplit=1)[-1],
                rel_path=item.destination_rel_path,
                media_type=media_type,
                size_bytes=item.source_size_bytes,
                sha256=sha256,
            )
            self.session.add(media)
            self.session.flush()
        return media

    def _ingest_with_revision(
        self, ingest_id: str, expected_revision: int
    ) -> IngestJob:
        ingest = self.session.get(IngestJob, ingest_id, populate_existing=True)
        if ingest is None or ingest.revision != expected_revision:
            raise StaleRevision("ingest revision is stale")
        return ingest


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
