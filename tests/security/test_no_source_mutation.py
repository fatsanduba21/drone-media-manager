from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

from drone_media_manager.worker.handlers.ingest import IngestJobHandler


def test_ingest_handler_never_writes_to_source(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    partial = tmp_path / ".source.partial"
    final = tmp_path / "destination.mp4"
    source.write_bytes(b"source")
    partial.write_bytes(b"source")
    before = source.read_bytes()

    IngestJobHandler().execute(
        SimpleNamespace(
            payload={
                "items": [
                    {
                        "source": str(source),
                        "partial": str(partial),
                        "final": str(final),
                        "source_sha256": hashlib.sha256(before).hexdigest(),
                    }
                ]
            }
        )
    )

    assert source.read_bytes() == before
