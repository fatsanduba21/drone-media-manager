"""DJI ``djmd`` decoding uses synthetic protobuf packets; no ffmpeg is needed."""

from __future__ import annotations

import json
import math
import struct
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from drone_media_manager.grouping.embedded import (
    decode_packets,
    read_embedded_samples,
    summarize,
)


def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _field(number: int, wire: int, payload: bytes) -> bytes:
    key = _varint(number << 3 | wire)
    if wire == 2:
        return key + _varint(len(payload)) + payload
    return key + payload


def _message(number: int, *parts: bytes) -> bytes:
    return _field(number, 2, b"".join(parts))


def packet(
    lat: float, lon: float, altitude_m: float, gimbal: tuple[float, ...] | None = None
) -> bytes:
    """Mirror the validated DJI Flip layout: frame 3 > aircraft 3 / gimbal 4."""
    position = _message(
        1,
        _field(2, 1, struct.pack("<d", math.radians(lat))),
        _field(3, 1, struct.pack("<d", math.radians(lon))),
    )
    aircraft = _message(
        3,
        _field(1, 0, _varint(1)),
        _message(4, position),
        _message(5, _field(1, 5, struct.pack("<f", altitude_m * 1000))),
    )
    parts = [aircraft]
    if gimbal is not None:
        parts.append(
            _message(
                4,
                _message(
                    4,
                    *(
                        _field(n, 5, struct.pack("<f", value))
                        for n, value in enumerate(gimbal, start=1)
                    ),
                ),
            )
        )
    return _message(3, *parts)


def _quaternion(yaw_deg: float, pitch_deg: float) -> tuple[float, float, float, float]:
    cy, sy = math.cos(math.radians(yaw_deg) / 2), math.sin(math.radians(yaw_deg) / 2)
    cp, sp = (
        math.cos(math.radians(pitch_deg) / 2),
        math.sin(math.radians(pitch_deg) / 2),
    )
    return cy * cp, -sy * sp, cy * sp, sy * cp


def test_decodes_position_altitude_and_gimbal() -> None:
    samples = decode_packets(
        [
            (0, 42, packet(-21.5223, -46.6445, 1.6, _quaternion(-27.5, -19.3))),
            (42, 83, packet(-21.5224, -46.6446, 12.6)),
        ]
    )

    assert len(samples) == 2
    first = samples[0]
    assert (first.start_ms, first.end_ms) == (0, 42)
    assert math.isclose(first.latitude or 0, -21.5223, abs_tol=1e-9)
    assert math.isclose(first.longitude or 0, -46.6445, abs_tol=1e-9)
    assert math.isclose(first.altitude or 0, 1.6, abs_tol=1e-6)
    assert math.isclose(first.gimbal_yaw or 0, -27.5, abs_tol=0.01)
    assert math.isclose(first.gimbal_pitch or 0, -19.3, abs_tol=0.01)
    assert samples[1].gimbal_yaw is None and samples[1].gimbal_pitch is None


def test_skips_malformed_packets_and_rejects_null_island() -> None:
    samples = decode_packets(
        [
            (0, 40, b"\xff\xff\xff"),
            (40, 80, b"\x0b"),
            (80, 120, packet(0.0, 0.0, 5.0)),
            (120, 120, packet(-3.8, -32.4, 1.0)),
        ]
    )

    assert len(samples) == 1
    assert samples[0].latitude is None and samples[0].longitude is None
    assert summarize(samples).sample_count == 0


def test_summarize_reports_start_end_and_centroid() -> None:
    summary = summarize(
        decode_packets(
            [(0, 40, packet(-3.0, -32.0, 1.0)), (40, 80, packet(-5.0, -34.0, 1.0))]
        )
    )

    assert summary.sample_count == 2
    assert math.isclose(summary.start_lat or 0, -3.0)
    assert math.isclose(summary.end_lon or 0, -34.0)
    assert math.isclose(summary.centroid_lat or 0, -4.0)
    assert summary.start_time is None


def _runner(
    packets: list[bytes], *, streams: list[dict[str, Any]] | None = None
) -> Any:
    listing = {
        "packets": [
            {
                "pts_time": f"{index * 0.0417:.6f}",
                "duration_time": "0.041700",
                "size": str(len(p)),
            }
            for index, p in enumerate(packets)
        ]
    }
    calls: list[list[str]] = []

    def run(args: list[str], **_: object) -> SimpleNamespace:
        calls.append(args)
        if args[0] == "ffprobe" and "stream=index,codec_tag_string" in args:
            payload = {
                "streams": streams
                if streams is not None
                else [
                    {"index": 0, "codec_tag_string": "hvc1"},
                    {"index": 1, "codec_tag_string": "djmd"},
                ]
            }
            return SimpleNamespace(stdout=json.dumps(payload).encode())
        if args[0] == "ffprobe":
            return SimpleNamespace(stdout=json.dumps(listing).encode())
        return SimpleNamespace(stdout=b"".join(packets))

    run.calls = calls  # type: ignore[attr-defined]
    return run


def test_read_embedded_samples_splits_track_by_packet_size(tmp_path: Path) -> None:
    runner = _runner([packet(-21.5, -46.6, 2.0), packet(-21.6, -46.7, 3.0)])

    samples = read_embedded_samples(tmp_path / "clip.mp4", runner=runner)

    assert [(s.start_ms, s.end_ms) for s in samples] == [(0, 42), (42, 84)]
    assert math.isclose(samples[1].latitude or 0, -21.6)
    assert "0:1" in runner.calls[-1]


def test_read_embedded_samples_without_djmd_or_on_failure_is_empty(
    tmp_path: Path,
) -> None:
    clip = tmp_path / "clip.mp4"
    no_track = _runner(
        [packet(-1, -1, 1)], streams=[{"index": 0, "codec_tag_string": "avc1"}]
    )
    assert read_embedded_samples(clip, runner=no_track) == []

    def missing_ffprobe(*_: object, **__: object) -> None:
        raise FileNotFoundError("ffprobe")

    assert read_embedded_samples(clip, runner=missing_ffprobe) == []

    def failing(args: list[str], **_: object) -> None:
        raise subprocess.CalledProcessError(1, args)

    assert read_embedded_samples(clip, runner=failing) == []


def test_read_embedded_samples_rejects_size_mismatch(tmp_path: Path) -> None:
    good = packet(-21.5, -46.6, 2.0)
    runner = _runner([good])

    def truncated(args: list[str], **kwargs: object) -> SimpleNamespace:
        result: SimpleNamespace = runner(args, **kwargs)
        if args[0] == "ffmpeg":
            result.stdout = result.stdout[:-3]
        return result

    assert read_embedded_samples(tmp_path / "clip.mp4", runner=truncated) == []
