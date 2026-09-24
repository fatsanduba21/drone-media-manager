"""Small, tolerant parser for DJI-style SRT location samples."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

_LAT = re.compile(r"\b(?:latitude|lat)\s*[:=]\s*(-?\d+(?:\.\d+)?)", re.IGNORECASE)
_LON = re.compile(r"\b(?:longitude|lon|lng)\s*[:=]\s*(-?\d+(?:\.\d+)?)", re.IGNORECASE)
_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})(?:[.,]\d+)?")


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
