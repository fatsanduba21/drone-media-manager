from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

from drone_media_manager.worker.handlers.ingest import IngestJobHandler


def test_repeat_import_reuses_identical_final_without_duplicate_files(
    tmp_path: Path,
) -> None:
    source = tmp_path / "clip.mp4"
    partial = tmp_path / ".clip.partial"
    final = tmp_path / "clip.mp4.final"
    source.write_bytes(b"source")
    partial.write_bytes(b"source")
    job = SimpleNamespace(
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

    first = IngestJobHandler().execute(job)
    partial.write_bytes(b"source")
    second = IngestJobHandler().execute(job)

    assert first.status == second.status == "VERIFIED"
    assert final.read_bytes() == b"source"
