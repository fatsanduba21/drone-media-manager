from __future__ import annotations

import json
from pathlib import Path

import pytest

from drone_media_manager.cli.organize import main


def test_plan_prints_preview_without_writing_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "photo.jpg").write_bytes(b"photo")
    omv = tmp_path / "omv"
    omv.mkdir()

    assert (
        main(
            [
                "plan",
                "--source",
                str(source),
                "--trip",
                "Trip",
                "--poi",
                "Place",
                "--output-omv",
                str(omv),
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["files"][0]["status"] == "CREATE"
    assert report["manifest_preview"]["assets"][0]["classification"] == "FOTOS"
    assert not (omv / "trip").exists()
