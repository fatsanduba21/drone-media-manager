"""Small, tolerant parser for DJI-style SRT location samples."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime

_LAT = re.compile(r"\b(?:latitude|lat)\s*[:=]\s*(-?\d+(?:\.\d+)?)", re.IGNORECASE)
_LON = re.compile(r"\b(?:longitude|lon|lng)\s*[:=]\s*(-?\d+(?:\.\d+)?)", re.IGNORECASE)
_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})(?:[.,]\d+)?")
_CUE = re.compile(
    r"(\d{2,}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2,}):(\d{2}):(\d{2})[,.](\d{3})"
)


@dataclass(frozen=True)
class TelemetrySample:
    start_ms: int
    end_ms: int
    latitude: float | None = None
    longitude: float | None = None
    altitude: float | None = None
    yaw: float | None = None
    gimbal_pitch: float | None = None
    gimbal_yaw: float | None = None
    heading: float | None = None
    speed: float | None = None


def parse_samples(content: str) -> list[TelemetrySample]:
    """Keep cue time and available observations; absent fields are never zero."""
    samples = []
    for block in re.split(r"\r?\n[ \t]*\r?\n", content):
        cue = _CUE.search(block)
        if not cue:
            continue
        parts = [int(value) for value in cue.groups()]
        if any(parts[i] >= 60 for i in (1, 2, 5, 6)):
            continue
        start, end = [
            ((parts[i] * 60 + parts[i + 1]) * 60 + parts[i + 2]) * 1000 + parts[i + 3]
            for i in (0, 4)
        ]
        if end <= start:
            continue

        def number(names: str, text: str = block) -> float | None:
            match = re.search(
                r"\b(?:" + names + r")\s*[:=]\s*(-?\d+(?:\.\d+)?)(?=\s|\]|<|$)",
                text,
                re.IGNORECASE,
            )
            value = float(match[1]) if match else None
            return value if value is not None and math.isfinite(value) else None

        lat, lon = number("latitude|lat"), number("longitude|lon|lng")
        if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            lat = lon = None
        samples.append(
            TelemetrySample(
                start,
                end,
                lat,
                lon,
                number("rel_alt|relative_altitude|altitude"),
                number("drone_yaw|yaw"),
                number("gimbal_pitch|gb_pitch"),
                number("gimbal_yaw|gb_yaw"),
                number("heading"),
                number("hs|speed"),
            )
        )
    return samples


@dataclass(frozen=True)
class TelemetrySummary:
    sample_count: int
    start_lat: float | None = None
    start_lon: float | None = None
    end_lat: float | None = None
    end_lon: float | None = None
    centroid_lat: float | None = None
    centroid_lon: float | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None


def parse_srt(content: str) -> TelemetrySummary:
    """Extract valid GPS samples; malformed subtitles are simply ignored."""
    points: list[tuple[float, float, datetime | None]] = []
    for block in re.split(r"\r?\n[ \t]*\r?\n", content):
        latitude = _LAT.search(block)
        longitude = _LON.search(block)
        if latitude is None or longitude is None:
            continue
        lat, lon = float(latitude.group(1)), float(longitude.group(1))
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        match = _DATE.search(block)
        try:
            timestamp = (
                datetime.fromisoformat(f"{match.group(1)}T{match.group(2)}")
                if match
                else None
            )
        except ValueError:
            timestamp = None
        points.append((lat, lon, timestamp))
    if not points:
        return TelemetrySummary(0)
    times = [point[2] for point in points if point[2] is not None]
    return TelemetrySummary(
        sample_count=len(points),
        start_lat=points[0][0],
        start_lon=points[0][1],
        end_lat=points[-1][0],
        end_lon=points[-1][1],
        centroid_lat=sum(point[0] for point in points) / len(points),
        centroid_lon=sum(point[1] for point in points) / len(points),
        start_time=times[0] if times else None,
        end_time=times[-1] if times else None,
    )
