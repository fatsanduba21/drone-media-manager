"""Explainable consecutive-clip boundary suggestions."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import pairwise

ALGORITHM_VERSION = "grouping-v1"
TIME_GAP_SECONDS = 30 * 60
GPS_GAP_METERS = 500
_NUMBER = re.compile(r"(\d+)(?!.*\d)")
_CAMERA_NUMBER = re.compile(
    r"(?:^|[_-])(?:DJI|VID|IMG|DSC)[_-](\d{3,6})(?=[_-]|$)", re.IGNORECASE
)
_LEADING_NUMBER = re.compile(r"^(\d{1,6})(?=[_-]|$)")


@dataclass(frozen=True)
class ClipSignal:
    asset_id: str
    filename: str
    captured_at: datetime | None
    latitude: float | None
    longitude: float | None
    end_at: datetime | None = None
    end_lat: float | None = None
    end_lon: float | None = None


@dataclass
class SuggestedRange:
    clips: list[ClipSignal] = field(default_factory=list)
    evidence: dict[str, float | int] = field(default_factory=dict)
    confidence: float | None = None


def sequence_number(filename: str) -> int | None:
    stem = filename.rsplit(".", 1)[0]
    match = (
        _CAMERA_NUMBER.search(stem)
        or _LEADING_NUMBER.search(stem)
        or _NUMBER.search(stem)
    )
    return int(match.group(1)) if match else None


def natural_key(filename: str) -> tuple[object, ...]:
    return tuple(
        int(part) if part.isdigit() else part.casefold()
        for part in re.split(r"(\d+)", filename)
    )


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _distance(a: ClipSignal, b: ClipSignal) -> float | None:
    lat_a = a.end_lat if a.end_lat is not None else a.latitude
    lon_a = a.end_lon if a.end_lon is not None else a.longitude
    if lat_a is None or lon_a is None or b.latitude is None or b.longitude is None:
        return None
    lat1, lat2 = math.radians(lat_a), math.radians(b.latitude)
    dlat = lat2 - lat1
    dlon = math.radians(b.longitude - lon_a)
    hav = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    return 2 * 6_371_000 * math.asin(min(1, math.sqrt(hav)))


def suggest_ranges(clips: list[ClipSignal]) -> list[SuggestedRange]:
    """Keep catalog order; split only at observable, explainable boundaries."""
    if not clips:
        return []
    groups = [SuggestedRange(clips=[clips[0]])]
    for previous, current in pairwise(clips):
        evidence: dict[str, float | int] = {}
        before, after = (
            sequence_number(previous.filename),
            sequence_number(current.filename),
        )
        if (
            before is not None
            and after is not None
            and (after < before or after - before > 1)
        ):
            evidence["sequence_gap"] = after - before
        previous_time = previous.end_at or previous.captured_at
        if previous_time is not None and current.captured_at is not None:
            seconds = (_utc(current.captured_at) - _utc(previous_time)).total_seconds()
            if seconds < 0 or seconds > TIME_GAP_SECONDS:
                evidence["time_gap_s"] = seconds
        distance = _distance(previous, current)
        if distance is not None and distance > GPS_GAP_METERS:
            evidence["gps_distance_m"] = round(distance, 1)
        if evidence:
            groups.append(
                SuggestedRange(
                    clips=[current],
                    evidence=evidence,
                    confidence=None,
                )
            )
        else:
            groups[-1].clips.append(current)
    return groups
