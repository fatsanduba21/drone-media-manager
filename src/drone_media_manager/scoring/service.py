"""Small heuristics; absent evidence stays absent, never a quality penalty."""

from __future__ import annotations

import math
from statistics import mean

from PIL import Image, ImageFilter, ImageStat

from drone_media_manager.grouping.telemetry import TelemetrySample

ALGORITHM_VERSION = "scoring-v1"
COMPONENTS = ("technical", "motion", "people", "duration", "composition", "uniqueness")
DEFAULT_PROFILES: dict[str, dict[str, float]] = {
    "instagram": dict(zip(COMPONENTS, (30, 25, 10, 10, 15, 10))),
    "youtube": dict(zip(COMPONENTS, (25, 20, 0, 20, 20, 15))),
}


def validate_weights(weights: dict[str, float]) -> dict[str, float]:
    if (
        not weights
        or weights.keys() - set(COMPONENTS)
        or any(not math.isfinite(v) or not 0 <= v <= 100 for v in weights.values())
        or sum(weights.values()) <= 0
    ):
        raise ValueError("invalid_score_weights")
    return {key: weights.get(key, 0) for key in COMPONENTS}


def weighted_score(
    scores: dict[str, float | None], weights: dict[str, float]
) -> tuple[float | None, float]:
    available = {
        key: value
        for key, value in scores.items()
        if value is not None and weights.get(key, 0) > 0
    }
    total = sum(weights.get(key, 0) for key in available)
    if not total:
        return None, 0
    return round(
        sum(value * weights[key] for key, value in available.items()) / total, 1
    ), round(total / sum(weights.values()), 3)


def image_metrics(image: Image.Image) -> tuple[float, dict[str, object], int | None]:
    gray = image.convert("L").resize((128, 128))
    histogram = gray.histogram()
    clipped = (sum(histogram[:8]) + sum(histogram[248:])) / (128 * 128)
    edges = gray.filter(ImageFilter.FIND_EDGES).crop((1, 1, 127, 127))
    edge_mean = ImageStat.Stat(edges).mean[0]
    sharpness = min(100.0, edge_mean * 5)
    exposure = 100 * (1 - clipped)
    # ponytail: one thumbnail misses changes inside a take; sample video frames
    # when a calibrated temporal quality evaluation becomes necessary.
    score = round((sharpness + exposure) / 2, 1)
    small = gray.resize((9, 8))
    fingerprint = None
    if ImageStat.Stat(gray).stddev[0] >= 5:
        pixels = small.tobytes()
        fingerprint = sum(
            int(pixels[y * 9 + x] > pixels[y * 9 + x + 1]) << (y * 8 + x)
            for y in range(8)
            for x in range(8)
        )
    return (
        score,
        {
            "scope": "single_thumbnail",
            "sharpness": round(sharpness, 1),
            "exposure": round(exposure, 1),
            "clipped_fraction": round(clipped, 4),
            "formula": "(min(100, mean_edges * 5) + 100 * (1 - clipped_fraction)) / 2",
        },
        fingerprint,
    )


def motion_metrics(
    samples: list[TelemetrySample],
) -> tuple[float | None, dict[str, object]]:
    penalties: dict[str, float] = {}
    for field, scale in (
        ("yaw", 30),
        ("gimbal_yaw", 30),
        ("gimbal_pitch", 20),
        ("speed", 5),
    ):
        changes = []
        for a, b, c in zip(samples, samples[1:], samples[2:]):
            values = [getattr(s, field) for s in (a, b, c)]
            dt1, dt2 = (
                (b.start_ms - a.start_ms) / 1000,
                (c.start_ms - b.start_ms) / 1000,
            )
            if any(v is None or not math.isfinite(v) for v in values) or not (
                0 < dt1 <= 5 and 0 < dt2 <= 5
            ):
                continue
            d1, d2 = values[1] - values[0], values[2] - values[1]
            if field in {"yaw", "gimbal_yaw"}:
                d1, d2 = (d1 + 180) % 360 - 180, (d2 + 180) % 360 - 180
            # Speed samples yield acceleration; angles yield angular acceleration.
            change = (
                (abs(d1 / dt1) + abs(d2 / dt2)) / 2
                if field == "speed"
                else abs(d2 / dt2 - d1 / dt1) / ((dt1 + dt2) / 2)
            )
            changes.append(change)
        if changes:
            penalties[field] = min(1.0, mean(changes) / scale)
    if not penalties:
        return None, {"reason": "insufficient_timed_telemetry"}
    return round(100 * (1 - mean(penalties.values())), 1), {
        "normalized_penalties": penalties,
        "sample_count": len(samples),
        "formula": "100 * (1 - mean(penalties)); angular acceleration scales 30/20 deg/s², acceleration scale 5 m/s²",
    }


def compare_takes(rows: list[dict[str, object]]) -> None:
    """Annotate candidate peers, never infer equivalence from context alone."""
    pools: dict[tuple[object, ...], list[dict[str, object]]] = {}
    for row in rows:
        row["similar_takes"] = []
        row["uniqueness_score"] = None
        context = row["context"]
        assert isinstance(context, dict)
        if not all(
            context.get(k) and str(context[k]).upper() != "UNKNOWN"
            for k in ("location_group_id", "movement", "subject")
        ):
            continue
        key = tuple(
            context[k]
            for k in (
                "trip_id",
                "location_group_id",
                "movement",
                "subject",
                "media_type",
            )
        )
        pools.setdefault(key, []).append(row)
    # ponytail: pairwise within editorial context; index fingerprints if a single
    # context grows beyond normal trip-sized batches.
    for pool in pools.values():
        for row in pool:
            peers = []
            distances = []
            if row["fingerprint"] is None:
                continue
            for other in pool:
                if row is other or other["fingerprint"] is None:
                    continue
                distance = (
                    int(str(row["fingerprint"])) ^ int(str(other["fingerprint"]))
                ).bit_count()
                distances.append(distance)
                if distance <= 8:
                    peers.append({"asset_id": other["asset_id"], "distance": distance})
            row["similar_takes"] = sorted(
                peers, key=lambda p: (p["distance"], p["asset_id"])
            )
            if distances:
                row["uniqueness_score"] = round(min(100, min(distances) / 32 * 100), 1)
