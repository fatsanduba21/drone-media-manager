"""Stationary head/tail trim suggestions and LosslessCut project output."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from drone_media_manager.cli.segments import main
from drone_media_manager.grouping.telemetry import TelemetrySample
from drone_media_manager.segments.sidecar import plan_projects, write_project
from drone_media_manager.segments.trim import (
    TrimRule,
    losslesscut_project,
    suggest_trim,
)

STEM = "DJI_20260605111039_0236_D"
FRAME_MS = 40
METRE_LAT = 1 / 111_320


def flight(
    hover_s: float, move_s: float, tail_s: float, speed: float = 2.0, **kw: float
) -> list[TelemetrySample]:
    """Hover, fly north at ``speed`` m/s, then hover again."""
    samples = []
    total = hover_s + move_s + tail_s
    for frame in range(int(total * 1000 / FRAME_MS)):
        t = frame * FRAME_MS / 1000
        moved = min(max(t - hover_s, 0), move_s) * speed
        samples.append(
            TelemetrySample(
                frame * FRAME_MS,
                (frame + 1) * FRAME_MS,
                -21.5 + moved * METRE_LAT,
                -46.6,
                10.0,
                gimbal_pitch=kw.get("pitch", 0.0),
                gimbal_yaw=kw.get("yaw", 0.0),
            )
        )
    return samples


def test_trims_hover_before_and_after_motion() -> None:
    keep = suggest_trim(flight(3, 20, 4))

    assert keep is not None
    start, end = keep
    assert 3000 <= start <= 3750  # Motion onset plus the 0.5 s lead-in.
    assert 22500 <= end <= 23500


def test_gimbal_pan_counts_as_motion_but_nadir_yaw_noise_does_not() -> None:
    hovering = flight(5, 0, 0)
    panning = [
        TelemetrySample(
            s.start_ms,
            s.end_ms,
            s.latitude,
            s.longitude,
            s.altitude,
            gimbal_pitch=-20.0,
            gimbal_yaw=s.start_ms / 100,
        )
        for s in hovering
    ]
    noisy_nadir = [
        TelemetrySample(
            s.start_ms,
            s.end_ms,
            s.latitude,
            s.longitude,
            s.altitude,
            gimbal_pitch=-90.0,
            gimbal_yaw=(s.start_ms * 37) % 360,
        )
        for s in hovering
    ]

    assert suggest_trim(panning) is not None
    assert suggest_trim(noisy_nadir) is None
    assert suggest_trim(hovering) is None


def test_short_motion_is_not_a_take() -> None:
    assert suggest_trim(flight(3, 1.5, 3)) is None
    assert suggest_trim(flight(3, 1.5, 3), TrimRule(min_keep_ms=500)) is not None


def test_losslesscut_project_layout() -> None:
    document = json.loads(losslesscut_project("clip.MP4", 30000, (3500, 25000)))

    assert document["version"] == 2 and document["mediaFileName"] == "clip.MP4"
    assert [(s["start"], s["end"], s["selected"]) for s in document["cutSegments"]] == [
        (0, 3.5, False),
        (3.5, 25.0, True),
        (25.0, 30.0, False),
    ]


def _srt(samples: list[TelemetrySample]) -> str:
    def clock(ms: int) -> str:
        return f"00:{ms // 60000:02}:{ms // 1000 % 60:02},{ms % 1000:03}"

    return "\n\n".join(
        f"{i + 1}\n{clock(s.start_ms)} --> {clock(s.end_ms)}\n"
        f"[latitude: {s.latitude:.7f}] [longitude: {s.longitude}] [rel_alt: 10.0]"
        for i, s in enumerate(samples)
    )


def test_plan_projects_writes_to_output_folder_and_keeps_existing(
    tmp_path: Path,
) -> None:
    originals, edited = tmp_path / "originais", tmp_path / "Editados"
    originals.mkdir()
    edited.mkdir()
    (originals / f"{STEM}.MP4").write_bytes(b"video")
    (originals / f"{STEM}.SRT").write_text(_srt(flight(3, 20, 4)), encoding="utf-8")
    (originals / "DJI_20260605111705_0241_D.MP4").write_bytes(b"no telemetry")
    (originals / f"{STEM}-00.00.03.000-00.00.20.000.MP4").write_bytes(b"a cut")
    (edited / "DJI_20260605111809_0242_D-proj.llc").write_text("mine")
    (originals / "DJI_20260605111809_0242_D.MP4").write_bytes(b"video")

    plans = {p.original.name[19:23]: p for p in plan_projects(originals, edited)}

    assert set(plans) == {"0236", "0241", "0242"}  # The cut segment is skipped.
    assert plans["0242"].status == "EXISTS"
    assert plans["0241"].status == "NO_TELEMETRY"
    plan = plans["0236"]
    assert plan.status == "CREATE" and plan.project.parent == edited
    assert write_project(plan) == "CREATED"
    assert write_project(plan) == "EXISTS"
    project = json.loads(plan.project.read_text(encoding="utf-8"))
    assert project["mediaFileName"] == f"{STEM}.MP4"
    assert (edited / "DJI_20260605111809_0242_D-proj.llc").read_text() == "mine"


def test_cli_suggest_dry_run_then_apply(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / f"{STEM}.MP4").write_bytes(b"video")
    (tmp_path / f"{STEM}.SRT").write_text(_srt(flight(3, 20, 4)), encoding="utf-8")
    project = tmp_path / f"{STEM}-proj.llc"

    assert main(["suggest", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["items"][0]["status"] == "CREATE"
    assert not project.exists()

    assert main(["suggest", str(tmp_path), "--apply"]) == 0
    assert json.loads(capsys.readouterr().out)["items"][0]["status"] == "CREATED"
    assert project.exists()
    assert main(["suggest", str(tmp_path), "--output", str(tmp_path / "x")]) == 2
