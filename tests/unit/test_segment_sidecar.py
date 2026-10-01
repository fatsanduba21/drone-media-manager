"""LosslessCut segment sidecars; synthetic files only, no ffmpeg or NAS."""

from __future__ import annotations

import json
import math
import struct
from datetime import datetime
from pathlib import Path

import pytest

from drone_media_manager.cli.segments import main
from drone_media_manager.grouping.embedded import decode_track
from drone_media_manager.grouping.telemetry import (
    TelemetrySample,
    parse_samples,
    parse_srt,
)
from drone_media_manager.segments.sidecar import (
    SidecarPlan,
    parse_segment_name,
    plan_folder,
    render_srt,
    slice_samples,
    write_sidecar,
)

STEM = "DJI_20260604171420_0223_D"


def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if not value:
            return bytes(out + bytes([byte]))
        out.append(byte | 0x80)


def _msg(number: int, payload: bytes) -> bytes:
    return _varint(number << 3 | 2) + _varint(len(payload)) + payload


def _frame(clock_us: int, lat: float, lon: float) -> bytes:
    header = _msg(1, _varint(2 << 3) + _varint(clock_us))
    position = _msg(
        1,
        _varint(2 << 3 | 1)
        + struct.pack("<d", math.radians(lat))
        + _varint(3 << 3 | 1)
        + struct.pack("<d", math.radians(lon)),
    )
    aircraft = _msg(3, _msg(4, position))
    return _msg(3, header + aircraft)


def djmd_dump(seconds: int, fps: int = 10) -> bytes:
    """LosslessCut-style dump: a file header then one field-3 message per frame."""
    step = 1_000_000 // fps
    frames = b"".join(
        _frame(5_000_000 + i * step, -21.5 - i * 1e-6, -46.6)
        for i in range(seconds * fps)
    )
    return _msg(1, b"\x0a\x03abc") + frames


def test_parse_segment_name_variants() -> None:
    assert parse_segment_name(f"{STEM}-00.00.03.653-00.00.12.878-seg2.MP4") == (
        parse_segment_name(f"{STEM}-00.00.03.653-00.00.12.878.mp4")
    )
    name = parse_segment_name(f"{STEM}-00.01.02.865-00.01.32.381-seg5.MP4")
    assert name is not None
    assert (name.stem, name.start_ms, name.end_ms) == (STEM, 62865, 92381)
    assert parse_segment_name(f"{STEM}.MP4") is None
    assert parse_segment_name(f"{STEM}-00.00.02.443.jpg") is None
    assert parse_segment_name(f"{STEM}-00.00.09.000-00.00.03.000.MP4") is None


def test_decode_track_uses_frame_clock() -> None:
    samples = decode_track(djmd_dump(2))

    assert len(samples) == 20
    assert (samples[0].start_ms, samples[0].end_ms) == (0, 100)
    assert samples[-1].end_ms == 2000
    assert math.isclose(samples[0].latitude or 0, -21.5)
    assert decode_track(b"\x08\x01") == []
    assert decode_track(djmd_dump(1)[:-2]) == []


def test_slice_rebases_and_clips() -> None:
    samples = [TelemetrySample(i * 100, (i + 1) * 100, 1.0, 2.0) for i in range(10)]

    sliced = slice_samples(samples, 250, 500)

    assert [(s.start_ms, s.end_ms) for s in sliced] == [
        (0, 50),
        (50, 150),
        (150, 250),
    ]


def test_render_round_trips_through_dmm_parsers() -> None:
    samples = [
        TelemetrySample(0, 42, -21.5223, -46.6445, 5.8, gimbal_yaw=-0.0001),
        TelemetrySample(42, 84, -21.5224, -46.6446, 6.0, gimbal_pitch=-19.3),
        TelemetrySample(84, 126, None, None, 6.1),
    ]

    content = render_srt(samples, datetime(2026, 6, 4, 17, 14, 23, 653000))  # noqa: DTZ001

    parsed = parse_samples(content)
    assert [(s.start_ms, s.end_ms) for s in parsed] == [(0, 42), (42, 84), (84, 126)]
    assert parsed[0].latitude == -21.5223 and parsed[2].latitude is None
    assert parsed[1].gimbal_pitch == -19.3 and parsed[0].gimbal_yaw == 0.0
    assert "-0.0" not in content
    summary = parse_srt(content)
    assert summary.sample_count == 2
    assert summary.start_time == datetime(2026, 6, 4, 17, 14, 23)  # noqa: DTZ001


def _parent_srt(seconds: int) -> str:
    return "\n\n".join(
        f"{i + 1}\n00:00:{i:02},000 --> 00:00:{i + 1:02},000\n"
        f"[latitude: -21.5{i:02}] [longitude: -46.6] [rel_alt: {i}.0]"
        for i in range(seconds)
    )


def test_plan_prefers_parent_srt_and_aligns_to_keyframe(tmp_path: Path) -> None:
    edited = tmp_path / "Editados"
    edited.mkdir()
    (tmp_path / f"{STEM}.SRT").write_text(_parent_srt(20), encoding="utf-8")
    (edited / f"{STEM}-stream-1-data-djmd.bin").write_bytes(djmd_dump(20))
    segment = edited / f"{STEM}-00.00.05.000-00.00.10.000-seg2.MP4"
    segment.write_bytes(b"video")
    (edited / f"{STEM}-00.00.02.443.jpg").write_bytes(b"jpg")

    # The lossless cut really starts 1 s earlier, at the preceding keyframe.
    [plan] = plan_folder(edited, prober=lambda _: 6000)

    assert plan.status == "CREATE"
    assert plan.source == f"{STEM}.SRT"
    assert (plan.start_ms, plan.end_ms) == (4000, 10000)
    assert plan.sidecar == segment.with_suffix(".SRT")
    assert plan.content is not None
    first = parse_samples(plan.content)[0]
    assert first.latitude == -21.504 and first.altitude == 4.0
    assert "2026-06-04 17:14:24.000" in plan.content


def test_plan_falls_back_to_djmd_dump_and_ignores_far_keyframes(
    tmp_path: Path,
) -> None:
    (tmp_path / f"{STEM}-stream-1-data-djmd.bin").write_bytes(djmd_dump(20))
    (tmp_path / f"{STEM}-00.00.10.000-00.00.12.000.MP4").write_bytes(b"v")

    [plan] = plan_folder(tmp_path, prober=lambda _: 9000)  # 7 s early: implausible

    assert plan.source == f"{STEM}-stream-1-data-djmd.bin"
    assert (plan.start_ms, plan.end_ms) == (10000, 12000)
    assert plan.sample_count == 20


def test_plan_reports_missing_telemetry_and_existing_sidecars(tmp_path: Path) -> None:
    (tmp_path / "OTHER-00.00.01.000-00.00.02.000.MP4").write_bytes(b"v")
    (tmp_path / f"{STEM}-00.00.01.000-00.00.02.000.MP4").write_bytes(b"v")
    (tmp_path / f"{STEM}-00.00.01.000-00.00.02.000.srt").write_text("mine")

    statuses = {
        p.segment.name[:5]: p.status for p in plan_folder(tmp_path, prober=None)
    }

    assert statuses == {"DJI_2": "EXISTS", "OTHER": "NO_TELEMETRY"}


def test_write_sidecar_never_overwrites(tmp_path: Path) -> None:
    target = tmp_path / "clip.SRT"
    plan = SidecarPlan(tmp_path / "clip.MP4", target, "CREATE", content="new\n")

    assert write_sidecar(plan) == "CREATED"
    assert target.read_text(encoding="utf-8") == "new\n"
    target.write_text("edited by hand", encoding="utf-8")
    assert write_sidecar(plan) == "EXISTS"
    assert target.read_text(encoding="utf-8") == "edited by hand"


def test_cli_is_dry_run_unless_apply(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / f"{STEM}-stream-1-data-djmd.bin").write_bytes(djmd_dump(5))
    segment = tmp_path / f"{STEM}-00.00.01.000-00.00.03.000.MP4"
    segment.write_bytes(b"v")

    assert main(["srt", str(tmp_path), "--no-probe"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["segments"][0]["status"] == "CREATE"
    assert not segment.with_suffix(".SRT").exists()

    assert main(["srt", str(tmp_path), "--no-probe", "--apply"]) == 0
    assert json.loads(capsys.readouterr().out)["segments"][0]["status"] == "CREATED"
    assert parse_samples(segment.with_suffix(".SRT").read_text(encoding="utf-8"))

    assert main(["srt", str(tmp_path / "missing")]) == 2
