"""Per-frame telemetry embedded by DJI in the MP4 ``djmd`` data track.

The DJI Flip writes one protobuf message per video frame (``dvtm_flip.proto``).
Field paths were validated against the same clip's SRT: GPS in radians,
relative altitude in millimetres and the gimbal attitude as a quaternion.
Other DJI models may use different paths; unknown layouts yield no samples.
"""

from __future__ import annotations

import json
import math
import struct
import subprocess
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from drone_media_manager.grouping.telemetry import TelemetrySample, TelemetrySummary

EMBEDDED_PARSER_VERSION = "djmd-flip-v1"
MAX_TRACK_BYTES = 64 * 1024 * 1024
_TIMEOUT_SECONDS = 120

_LATITUDE = (3, 3, 4, 1, 2)
_LONGITUDE = (3, 3, 4, 1, 3)
_RELATIVE_ALTITUDE_MM = (3, 3, 5, 1)
_GIMBAL_QUATERNION = (3, 4, 4)

Runner = Callable[..., Any]


def _varint(data: bytes, index: int) -> tuple[int, int]:
    result = shift = 0
    while True:
        if index >= len(data) or shift > 63:
            raise ValueError("truncated_varint")
        byte = data[index]
        index += 1
        result |= (byte & 0x7F) << shift
        shift += 7
        if byte < 0x80:
            return result, index


def _fields(data: bytes) -> dict[int, bytes | int]:
    """Return the first occurrence of each field; raise on malformed input."""
    fields: dict[int, bytes | int] = {}
    index = 0
    while index < len(data):
        key, index = _varint(data, index)
        number, wire = key >> 3, key & 7
        value: bytes | int
        if wire == 0:
            value, index = _varint(data, index)
        elif wire == 1:
            value, index = data[index : index + 8], index + 8
        elif wire == 2:
            size, index = _varint(data, index)
            value, index = data[index : index + size], index + size
        elif wire == 5:
            value, index = data[index : index + 4], index + 4
        else:
            raise ValueError("unsupported_wire_type")
        if index > len(data):
            raise ValueError("truncated_field")
        fields.setdefault(number, value)
    return fields


def _path(data: bytes, path: tuple[int, ...]) -> bytes | int | None:
    current: bytes | int | None = data
    for number in path:
        if not isinstance(current, bytes):
            return None
        current = _fields(current).get(number)
    return current


def _double(value: bytes | int | None) -> float | None:
    if not isinstance(value, bytes) or len(value) != 8:
        return None
    number: float = struct.unpack("<d", value)[0]
    return number if math.isfinite(number) else None


def _float(value: bytes | int | None) -> float | None:
    if not isinstance(value, bytes) or len(value) != 4:
        return None
    number: float = struct.unpack("<f", value)[0]
    return number if math.isfinite(number) else None


def _gimbal(packet: bytes) -> tuple[float | None, float | None]:
    raw = _path(packet, _GIMBAL_QUATERNION)
    if not isinstance(raw, bytes):
        return None, None
    fields = _fields(raw)
    w, x, y, z = (_float(fields.get(n)) or 0.0 for n in (1, 2, 3, 4))
    if w == x == y == z == 0.0:
        return None, None
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, 2 * (w * y - z * x)))))
    yaw = math.degrees(math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z)))
    return round(pitch, 2), round(yaw, 2)


def decode_packets(packets: Iterable[tuple[int, int, bytes]]) -> list[TelemetrySample]:
    """Decode ``(start_ms, end_ms, payload)`` packets; skip unreadable ones."""
    samples = []
    for start, end, payload in packets:
        if end <= start:
            continue
        try:
            lat_rad = _double(_path(payload, _LATITUDE))
            lon_rad = _double(_path(payload, _LONGITUDE))
            altitude_mm = _float(_path(payload, _RELATIVE_ALTITUDE_MM))
            gimbal_pitch, gimbal_yaw = _gimbal(payload)
        except ValueError:
            continue
        lat = math.degrees(lat_rad) if lat_rad is not None else None
        lon = math.degrees(lon_rad) if lon_rad is not None else None
        if (
            lat is None
            or lon is None
            or not (-90 <= lat <= 90 and -180 <= lon <= 180)
            or (lat == 0 and lon == 0)
        ):
            lat = lon = None
        samples.append(
            TelemetrySample(
                start,
                end,
                lat,
                lon,
                altitude_mm / 1000 if altitude_mm is not None else None,
                gimbal_pitch=gimbal_pitch,
                gimbal_yaw=gimbal_yaw,
            )
        )
    return samples


def read_embedded_samples(
    path: Path, *, runner: Runner = subprocess.run
) -> list[TelemetrySample]:
    """Read the ``djmd`` track with ffprobe/ffmpeg; any failure yields ``[]``."""
    try:
        probe = runner(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=index,codec_tag_string",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            check=True,
            timeout=_TIMEOUT_SECONDS,
        )
        streams = json.loads(probe.stdout).get("streams", [])
        index = next(
            int(stream["index"])
            for stream in streams
            if stream.get("codec_tag_string") == "djmd"
        )
        listing = runner(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                str(index),
                "-show_entries",
                "packet=pts_time,duration_time,size",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            check=True,
            timeout=_TIMEOUT_SECONDS,
        )
        entries = json.loads(listing.stdout).get("packets", [])
        payload = runner(
            [
                "ffmpeg",
                "-v",
                "error",
                "-nostdin",
                "-i",
                str(path),
                "-map",
                f"0:{index}",
                "-c",
                "copy",
                "-f",
                "data",
                "pipe:1",
            ],
            capture_output=True,
            check=True,
            timeout=_TIMEOUT_SECONDS,
        ).stdout
    except (
        OSError,
        ValueError,
        KeyError,
        StopIteration,
        TypeError,
        subprocess.SubprocessError,
    ):
        return []
    if not isinstance(payload, bytes) or len(payload) > MAX_TRACK_BYTES:
        return []
    packets = []
    offset = 0
    try:
        for entry in entries:
            size = int(entry["size"])
            start = round(float(entry["pts_time"]) * 1000)
            end = start + max(1, round(float(entry.get("duration_time", 0)) * 1000))
            packets.append((start, end, payload[offset : offset + size]))
            offset += size
    except (KeyError, TypeError, ValueError):
        return []
    if offset != len(payload):
        return []
    return decode_packets(packets)


def summarize(samples: list[TelemetrySample]) -> TelemetrySummary:
    """Positions only; wall-clock times come from the catalog capture time."""
    points = [
        (s.latitude, s.longitude)
        for s in samples
        if s.latitude is not None and s.longitude is not None
    ]
    if not points:
        return TelemetrySummary(0)
    return TelemetrySummary(
        sample_count=len(points),
        start_lat=points[0][0],
        start_lon=points[0][1],
        end_lat=points[-1][0],
        end_lon=points[-1][1],
        centroid_lat=sum(p[0] for p in points) / len(points),
        centroid_lon=sum(p[1] for p in points) / len(points),
    )
