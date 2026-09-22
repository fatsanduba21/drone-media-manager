from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from drone_media_manager.worker.handlers.ingest import IngestJobHandler


@pytest.mark.parametrize(
    ("failure", "expected_status"),
    [("destination_hash_mismatch", "FAILED"), ("source_disconnected", "FAILED")],
)
def test_failure_never_marks_ingest_verified(
    tmp_path: Path, failure: str, expected_status: str
) -> None:
    source = tmp_path / "clip.mp4"
    partial = tmp_path / ".clip.partial"
    final = tmp_path / "destination.mp4"
    source.write_bytes(b"source")
    partial.write_bytes(
        b"broken" if failure == "destination_hash_mismatch" else b"source"
    )
    if failure == "source_disconnected":
        source.unlink()

    result = IngestJobHandler().execute(
        SimpleNamespace(
            payload={
                "items": [
                    {
                        "source": str(source),
                        "partial": str(partial),
                        "final": str(final),
                        "source_sha256": hashlib.sha256(b"source").hexdigest(),
                    }
                ]
            }
        )
    )

    assert result.status == expected_status
    assert result.status != "VERIFIED"
    assert not final.exists()
