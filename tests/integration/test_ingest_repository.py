from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from drone_media_manager.db.base import Base
from drone_media_manager.db.models.ingest import IngestItem, IngestJob, Trip
from drone_media_manager.domain.enums import IngestStatus, PairStatus, SourceKind
from drone_media_manager.domain.errors import InvalidTransition, StaleRevision
from drone_media_manager.ingest.repository import IngestRepository


@pytest.fixture
def session(tmp_path: Path) -> Session:
    engine = create_engine(f"sqlite:///{tmp_path / 'ingest.sqlite3'}")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session
    engine.dispose()


@pytest.fixture
def trip(session: Session) -> Trip:
    value = Trip(name="Test trip", slug="test-trip", nas_rel_path="trips/test-trip")
    session.add(value)
    session.commit()
    return value


@pytest.fixture
def ingest_item(session: Session, trip: Trip) -> IngestItem:
    job = IngestJob(
        trip_id=trip.id,
        source_kind=SourceKind.LOCAL,
        source_fingerprint="a" * 64,
        bytes_total=100,
    )
    session.add(job)
    session.flush()
    item = IngestItem(
        ingest_job_id=job.id,
        source_rel_path="DCIM/clip.mp4",
        source_size_bytes=100,
        source_mtime_ns=1,
        source_file_identity="file-1",
        pair_status=PairStatus.VIDEO_WITHOUT_SRT,
        destination_rel_path="trips/test-trip/00_INBOX_ORIGINALS/DCIM/clip.mp4",
        partial_rel_path="trips/test-trip/00_INBOX_ORIGINALS/DCIM/.clip.partial",
    )
    session.add(item)
    session.commit()
    return item


@pytest.fixture
def repository(session: Session) -> IngestRepository:
    return IngestRepository(session)


def test_same_trip_and_source_fingerprint_is_unique(
    session: Session, trip: Trip
) -> None:
    session.add(
        IngestJob(
            trip_id=trip.id,
            source_kind=SourceKind.LOCAL,
            source_fingerprint="a" * 64,
        )
    )
    session.commit()
    session.add(
        IngestJob(
            trip_id=trip.id,
            source_kind=SourceKind.LOCAL,
            source_fingerprint="a" * 64,
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_item_checkpoint_requires_expected_revision(
    repository: IngestRepository, ingest_item: IngestItem
) -> None:
    with pytest.raises(StaleRevision):
        repository.checkpoint_item(
            ingest_item.id,
            expected_revision=99,
            bytes_copied=10,
        )


def test_ingest_transition_rejects_shortcuts_and_advances_revision(
    repository: IngestRepository, ingest_item: IngestItem
) -> None:
    ingest_id = ingest_item.ingest_job_id
    with pytest.raises(InvalidTransition):
        repository.transition_ingest(
            ingest_id,
            expected_revision=0,
            target=IngestStatus.VERIFIED,
        )

    copying = repository.transition_ingest(
        ingest_id,
        expected_revision=0,
        target=IngestStatus.COPYING,
    )
    assert (copying.status, copying.revision) == (IngestStatus.COPYING, 1)

    verifying = repository.transition_ingest(
        copying.id,
        expected_revision=copying.revision,
        target=IngestStatus.VERIFYING,
    )

    assert (verifying.status, verifying.revision) == (IngestStatus.VERIFYING, 2)


def test_checkpoint_advances_only_the_matching_item_revision(
    repository: IngestRepository, ingest_item: IngestItem
) -> None:
    checkpointed = repository.checkpoint_item(
        ingest_item.id,
        expected_revision=0,
        bytes_copied=10,
    )

    assert (checkpointed.bytes_copied, checkpointed.revision) == (10, 1)
    with pytest.raises(StaleRevision):
        repository.checkpoint_item(
            ingest_item.id,
            expected_revision=0,
            bytes_copied=20,
        )
