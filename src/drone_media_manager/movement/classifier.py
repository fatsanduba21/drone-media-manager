"""Conservative telemetry rules. Confidence is heuristic, not calibrated accuracy."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from itertools import pairwise
from statistics import mean, pstdev

from drone_media_manager.grouping.telemetry import TelemetrySample

ALGORITHM_VERSION = "movement-v1"
MOVEMENTS = (
    "ORBITA",
    "MEIA_ORBITA",
    "FOGUETE",
    "APROXIMACAO",
    "AFASTAMENTO",
    "TRAVELLING",
    "SOBREVOO",
    "PAN",
    "HOVER",
    "SUBIDA",
    "DESCIDA",
    "ESTATICO",
    "UNKNOWN",
)
WINDOW_MS = 5000


@dataclass(frozen=True)
class Suggestion:
    value: str
    confidence: float
    evidence: dict[str, object]
    algorithm_version: str = ALGORITHM_VERSION

    def data(self) -> dict[str, object]:
        return asdict(self)


def _angle_delta(a: float, b: float) -> float:
    return (b - a + 180) % 360 - 180


def _sweep(values: list[float]) -> float:
    return sum(abs(_angle_delta(a, b)) for a, b in pairwise(values))


def _xy(lat: float, lon: float, origin: tuple[float, float]) -> tuple[float, float]:
    return (
        math.radians((lon - origin[1] + 180) % 360 - 180)
        * 6371000
        * math.cos(math.radians(origin[0])),
        math.radians(lat - origin[0]) * 6371000,
    )


def _circle(
    points: list[tuple[float, float]], minimum_arc: float = 120
) -> dict[str, object] | None:
    """Least-squares circle fit, centered to avoid cancellation (2x2 system)."""
    mx, my = mean(p[0] for p in points), mean(p[1] for p in points)
    centered = [(x - mx, y - my) for x, y in points]
    xx = sum(x * x for x, y in centered)
    yy = sum(y * y for x, y in centered)
    xy = sum(x * y for x, y in centered)
    determinant = xx * yy - xy * xy
    if determinant <= 1e-6 * max(xx * yy, 1):
        return None
    bx = sum(x * (x * x + y * y) / 2 for x, y in centered)
    by = sum(y * (x * x + y * y) / 2 for x, y in centered)
    cx, cy = (bx * yy - by * xy) / determinant, (by * xx - bx * xy) / determinant
    radii = [math.hypot(x - cx, y - cy) for x, y in centered]
    radius = mean(radii)
    if radius < 5:
        return None
    angles = [math.degrees(math.atan2(y - cy, x - cx)) for x, y in centered]
    deltas = [_angle_delta(a, b) for a, b in pairwise(angles)]
    coverage = abs(sum(deltas))
    consistency = coverage / max(sum(abs(d) for d in deltas), 1)
    variation = pstdev(radii) / radius * 100
    if coverage < minimum_arc or variation > 15 or consistency < 0.9:
        return None
    return {
        "angular_coverage_deg": round(coverage, 2),
        "radius_m": round(radius, 2),
        "radius_variation_pct": round(variation, 2),
    }


def classify(
    samples: list[TelemetrySample],
    *,
    anchor: tuple[float, float] | None = None,
    minimum_arc: float = 120,
) -> Suggestion:
    evidence: dict[str, object] = {"sample_count": len(samples)}

    def result(
        value: str = "UNKNOWN",
        confidence: float = 0,
        reason: str = "insufficient_telemetry",
    ) -> Suggestion:
        return Suggestion(value, confidence, {**evidence, "reason": reason})

    if len(samples) < 3 or samples[-1].end_ms - samples[0].start_ms < 2000:
        return result()
    if any(
        b.start_ms <= a.start_ms or b.start_ms - a.end_ms > 2000
        for a, b in pairwise(samples)
    ):
        return result(reason="invalid_or_sparse_timing")
    if any(s.latitude is None or s.longitude is None for s in samples):
        return result(reason="missing_gps")
    origin = (samples[0].latitude, samples[0].longitude)
    assert origin[0] is not None and origin[1] is not None
    points = [
        _xy(s.latitude, s.longitude, (origin[0], origin[1]))
        for s in samples
        if s.latitude is not None and s.longitude is not None
    ]
    steps = [math.dist(a, b) for a, b in pairwise(points)]
    if any(
        d / ((b.start_ms - a.start_ms) / 1000) > 50
        for d, (a, b) in zip(steps, pairwise(samples))
    ):
        return result(reason="gps_jump")
    distance = sum(steps)
    extent = max(math.dist(points[0], p) for p in points)
    evidence.update(
        distance_m=round(distance, 2),
        displacement_m=round(math.dist(points[0], points[-1]), 2),
    )
    altitudes = [s.altitude for s in samples if s.altitude is not None]
    yaws = [s.yaw for s in samples if s.yaw is not None]
    pitches = [s.gimbal_pitch for s in samples if s.gimbal_pitch is not None]
    altitude_delta = (
        altitudes[-1] - altitudes[0] if len(altitudes) == len(samples) else None
    )
    yaw_delta = _sweep(yaws) if len(yaws) == len(samples) else None
    evidence.update(altitude_delta_m=altitude_delta, yaw_delta_deg=yaw_delta)
    if extent <= 3:
        if altitude_delta is not None and abs(altitude_delta) >= 4:
            if (
                altitude_delta > 0
                and len(pitches) == len(samples)
                and max(pitches) <= -70
                and yaw_delta is not None
                and yaw_delta < 15
            ):
                return result("FOGUETE", 0.8, "vertical_up_camera_down")
            return result(
                "SUBIDA" if altitude_delta > 0 else "DESCIDA",
                0.8,
                "vertical_translation",
            )
        if altitude_delta is None or max(altitudes) - min(altitudes) > 2:
            return result(reason="vertical_motion_unresolved")
        camera_yaws = [s.gimbal_yaw for s in samples if s.gimbal_yaw is not None]
        if (yaw_delta is not None and yaw_delta >= 20) or (
            len(camera_yaws) == len(samples) and _sweep(camera_yaws) >= 20
        ):
            return result("PAN", 0.8, "stationary_rotation")
        if (
            yaw_delta is not None
            and yaw_delta <= 5
            and len(pitches) == len(samples)
            and max(pitches) - min(pitches) <= 5
        ):
            return result(
                "ESTATICO" if max(abs(a) for a in altitudes) < 1 else "HOVER",
                0.7,
                "stable_position_and_orientation",
            )
        return result(reason="orientation_unresolved")
    if altitude_delta is None or max(altitudes) - min(altitudes) > 4:
        return result(reason="mixed_or_missing_vertical_motion")
    circle = (
        _circle(points, minimum_arc)
        if distance >= 15 and sum(step > 0.1 for step in steps) / len(steps) >= 0.9
        else None
    )
    if circle:
        evidence.update(circle)
        return result(
            "ORBITA"
            if float(str(circle["angular_coverage_deg"])) >= 270
            else "MEIA_ORBITA",
            0.8,
            "circular_translation",
        )
    if anchor is not None:
        target = _xy(*anchor, (origin[0], origin[1]))
        radii = [math.dist(p, target) for p in points]
        delta = radii[-1] - radii[0]
        radial_travel = sum(abs(b - a) for a, b in pairwise(radii))
        evidence.update(
            anchor_lat=anchor[0],
            anchor_lon=anchor[1],
            reference_source="HUMAN",
            radial_delta_m=round(delta, 2),
        )
        if (
            abs(delta) >= 8
            and abs(delta) / max(radial_travel, 1) >= 0.9
            and abs(delta) / max(distance, 1) >= 0.8
        ):
            return result(
                "AFASTAMENTO" if delta > 0 else "APROXIMACAO",
                0.75,
                "translation_relative_to_confirmed_anchor",
            )
    headings = [s.heading for s in samples if s.heading is not None]
    displacement = math.dist(points[0], points[-1])
    if (
        distance >= 8
        and displacement / distance >= 0.9
        and len(headings) == len(samples)
        and len(pitches) == len(samples)
        and yaw_delta is not None
        and yaw_delta <= 10
    ):
        bearing = math.degrees(
            math.atan2(points[-1][0] - points[0][0], points[-1][1] - points[0][1])
        )
        if all(abs(_angle_delta(bearing, heading)) <= 20 for heading in headings):
            evidence.update(
                gps_bearing_deg=round(bearing, 2),
                heading_delta_deg=round(_sweep(headings), 2),
            )
            if max(pitches) <= -70:
                return result("SOBREVOO", 0.7, "straight_translation_camera_down")
            if min(pitches) >= -60 and all(
                60 <= abs(_angle_delta(bearing, yaw)) <= 120 for yaw in yaws
            ):
                return result(
                    "TRAVELLING", 0.7, "lateral_translation_relative_to_camera"
                )
    return result(reason="no_reliable_movement_reference")


def segment_track(
    samples: list[TelemetrySample],
    *,
    duration_ms: int | None,
    anchor: tuple[float, float] | None = None,
) -> list[tuple[int, int, Suggestion]]:
    end = (
        duration_ms
        if duration_ms is not None and duration_ms > 0
        else max((s.end_ms for s in samples), default=0)
    )
    if end == 0:
        return []
    if end > 86_400_000:
        return [
            (0, end, Suggestion("UNKNOWN", 0, {"reason": "duration_exceeds_24_hours"}))
        ]
    # ponytail: 5s boundaries; use change-point detection when real labels justify it.
    whole = classify(samples, anchor=anchor)
    if (
        whole.value in {"ORBITA", "MEIA_ORBITA"}
        and samples[0].start_ms == 0
        and samples[-1].end_ms >= end
    ):
        return [(0, end, whole)]
    windows: list[tuple[int, int, Suggestion]] = []
    buckets: dict[int, list[TelemetrySample]] = {}
    for sample in samples:
        buckets.setdefault(sample.start_ms // WINDOW_MS, []).append(sample)
    for start in range(0, end, WINDOW_MS):
        stop = min(start + WINDOW_MS, end)
        window = buckets.get(start // WINDOW_MS, [])
        suggestion = classify(window, anchor=anchor, minimum_arc=20)
        if (
            not window
            or window[0].start_ms - start > 2000
            or stop - window[-1].end_ms > 2000
        ):
            suggestion = Suggestion("UNKNOWN", 0, {"reason": "missing_telemetry"})
        if windows and windows[-1][2].value == suggestion.value:
            before = windows.pop()
            windows.append(
                (
                    before[0],
                    stop,
                    Suggestion(
                        suggestion.value,
                        min(before[2].confidence, suggestion.confidence),
                        {"reason": "adjacent_windows", "window_ms": WINDOW_MS},
                    ),
                )
            )
        else:
            windows.append((start, stop, suggestion))
    result = []
    for start, stop, suggestion in windows:
        members = [s for s in samples if start <= s.start_ms < stop]
        if (
            members
            and members[0].start_ms - start <= 2000
            and stop - members[-1].end_ms <= 2000
        ):
            suggestion = classify(members, anchor=anchor)
        result.append((start, stop, suggestion))
    return result
