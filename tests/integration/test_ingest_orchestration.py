from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

from drone_media_manager.worker.handlers.ingest import IngestJobHandler


def test_claimed_ingest_verifies_and_promotes_without_mutating_source(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.mp4"
    partial = tmp_path / ".source.partial"
    final = tmp_path / "source.mp4.final"
    source.write_bytes(b"media")
    partial.write_bytes(b"media")

    result = IngestJobHandler().execute(
        SimpleNamespace(
            payload={
                "items": [
                    {
                        "source": str(source),
                        "partial": str(partial),
                        "final": str(final),
                        "source_sha256": hashlib.sha256(b"media").hexdigest(),
                    }
                ]
            }
        )
    )

    assert result.status == "VERIFIED"
    assert result.bytes_verified == 5
    assert source.read_bytes() == b"media"
    assert final.read_bytes() == b"media"
