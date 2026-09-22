"""Canonical, replay-safe manifests for verified ingests."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class ManifestItem:
    source_rel_path: str
    destination_rel_path: str
    size_bytes: int
    source_sha256: str | None
    destination_sha256: str | None
    pair_status: str
    status: str
    error: str | None


@dataclass(frozen=True, slots=True)
class IngestManifest:
    schema_version: int
    ingest_id: str
    source_kind: str
    source_fingerprint: str
    items: tuple[ManifestItem, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "ingest_id": self.ingest_id,
            "source_kind": self.source_kind,
            "source_fingerprint": self.source_fingerprint,
            "items": [asdict(item) for item in self.items],
        }


@dataclass(frozen=True, slots=True)
class ManifestWriteResult:
    status: str
    path: Path
    error_code: str | None = None


def build_manifest(ingest: Any) -> IngestManifest:
    items = tuple(
        ManifestItem(
            source_rel_path=str(item.source_rel_path),
            destination_rel_path=str(item.destination_rel_path),
            size_bytes=int(item.source_size_bytes),
            source_sha256=getattr(item, "source_sha256", None),
            destination_sha256=getattr(item, "destination_sha256", None),
            pair_status=str(item.pair_status),
            status=str(item.status),
            error=getattr(item, "error", None),
        )
        for item in getattr(ingest, "items", ())
    )
    return IngestManifest(
        schema_version=1,
        ingest_id=str(ingest.id),
        source_kind=str(ingest.source_kind),
        source_fingerprint=str(ingest.source_fingerprint),
        items=items,
    )


def write_manifest_atomic(
    manifest: IngestManifest, destination: Path
) -> ManifestWriteResult:
    payload = json.dumps(
        manifest.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.read_bytes() == payload:
            return ManifestWriteResult("IDENTICAL_EXISTING", destination)
        return ManifestWriteResult(
            "DIVERGENT_CONFLICT", destination, "existing_content_differs"
        )

    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError:
            if destination.read_bytes() == payload:
                return ManifestWriteResult("IDENTICAL_EXISTING", destination)
            return ManifestWriteResult(
                "DIVERGENT_CONFLICT", destination, "existing_content_differs"
            )
        return ManifestWriteResult("WRITTEN", destination)
    finally:
        if temporary.exists():
            temporary.unlink()
