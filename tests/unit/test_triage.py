"""Local format sorting before cutting; ffprobe is replaced by a fake prober."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from drone_media_manager.cli.organize import main
from drone_media_manager.triage import apply_sort, plan_sort

DIMENSIONS = {
    "land.MP4": (3840, 2160, None),
    "rotated.MP4": (2688, 1512, 90.0),
    "square.MP4": (1080, 1080, None),
}


def fake_prober(path: Path) -> dict[str, Any]:
    if path.name == "broken.MP4":
        raise ValueError("ffprobe failed")
    width, height, rotation = DIMENSIONS[path.name]
    return {
        "encoded_width": width,
        "encoded_height": height,
        "rotation_degrees": rotation,
    }


def _folder(tmp_path: Path) -> Path:
    for name in [*DIMENSIONS, "broken.MP4", "foto.JPG", "notes.txt"]:
        (tmp_path / name).write_bytes(name.encode())
    (tmp_path / "land.SRT").write_text("srt", encoding="utf-8")
    sorted_already = tmp_path / "YOUTUBE_16x9"
    sorted_already.mkdir()
    (sorted_already / "old.MP4").write_bytes(b"old")
    return tmp_path


def test_plan_classifies_like_the_organizer(tmp_path: Path) -> None:
    moves = {m.source.name: m for m in plan_sort(_folder(tmp_path), prober=fake_prober)}

    assert {name: m.target.parent.name for name, m in moves.items() if m.target} == {
        "land.MP4": "YOUTUBE_16x9",
        "rotated.MP4": "INSTAGRAM_9x16",
        "square.MP4": "OUTROS_REVISAR",
        "foto.JPG": "FOTOS",
    }
    assert moves["broken.MP4"].status == "ERROR"
    assert [s.name for s, _ in moves["land.MP4"].sidecars] == ["land.SRT"]
    assert "notes.txt" not in moves and "old.MP4" not in moves


def test_apply_moves_media_with_srt_and_never_replaces(tmp_path: Path) -> None:
    folder = _folder(tmp_path)
    (folder / "INSTAGRAM_9x16").mkdir()
    (folder / "INSTAGRAM_9x16" / "rotated.MP4").write_bytes(b"already there")

    results = {
        m.source.name: s for m, s in apply_sort(plan_sort(folder, prober=fake_prober))
    }

    assert results["land.MP4"] == "MOVED"
    assert (folder / "YOUTUBE_16x9" / "land.MP4").read_bytes() == b"land.MP4"
    assert (folder / "YOUTUBE_16x9" / "land.SRT").read_text(encoding="utf-8") == "srt"
    assert not (folder / "land.MP4").exists() and not (folder / "land.SRT").exists()
    assert results["rotated.MP4"] == "CONFLICT"
    assert (folder / "rotated.MP4").exists()
    assert (folder / "INSTAGRAM_9x16" / "rotated.MP4").read_bytes() == b"already there"
    assert (folder / "FOTOS" / "foto.JPG").exists()
    assert (folder / "YOUTUBE_16x9" / "old.MP4").read_bytes() == b"old"


def test_cli_sort_is_dry_run_by_default(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "land.MP4").write_bytes(b"v")
    monkeypatch.setattr(
        "drone_media_manager.cli.organize.probe_video",
        lambda path, ffprobe: fake_prober(path),
    )

    assert main(["sort", "--source", str(tmp_path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "PLANNED" and report["counts"] == {"YOUTUBE_16X9": 1}
    assert (tmp_path / "land.MP4").exists()

    assert main(["sort", "--source", str(tmp_path), "--apply"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "SORTED"
    assert (tmp_path / "YOUTUBE_16x9" / "land.MP4").exists()


def test_cli_plan_still_requires_trip_and_output(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(["plan", "--source", str(tmp_path)])
