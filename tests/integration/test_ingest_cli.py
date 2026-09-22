from __future__ import annotations

from pathlib import Path

from drone_media_manager.cli.worker import main


def test_worker_dry_run_requires_a_source_directory(tmp_path: Path) -> None:
    assert main(["ingest", "--dry-run", str(tmp_path)]) == 0
    assert main(["ingest", "--dry-run", str(tmp_path / "missing")]) == 2


def test_worker_verify_requires_an_ingest_id() -> None:
    assert main(["verify", "ingest-1"]) == 0
