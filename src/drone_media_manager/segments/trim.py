"""Suggest trimming the stationary start and end of a drone clip.

Calibrated on 22 hand-cut DJI Flip clips (LosslessCut projects): the editor
drops the hover before the drone gets moving and after it stops. Internal take
splits did not coincide with any telemetry change and are left to the editor.
Defaults: moving means >= 0.3 m/s horizontal, >= 0.5 m/s vertical or >= 2 deg/s
of gimbal motion, held for 1 s; the kept range starts 0.5 s after motion
begins, matching how the editor lets the drone gather speed.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass

from drone_media_manager.grouping.telemetry import TelemetrySample

_STEP_MS = 250
_SPAN_MS = 500
_EARTH_M_PER_DEG = 111_320
# Near nadir the gimbal yaw is ill-defined and jumps; ignore it there.
_NADIR_PITCH_DEG = 75


@dataclass(frozen=True)
class TrimRule:
    horizontal_mps: float = 0.3
    vertical_mps: float = 0.5
    gimbal_dps: float = 2.0
    hold_ms: int = 1000
    lead_in_ms: int = 500
    min_keep_ms: int = 2000


def _motion(samples: list[TelemetrySample], rule: TrimRule) -> list[bool | None]:
    first: dict[int, TelemetrySample] = {}
    for sample in samples:
        if sample.latitude is not None and sample.longitude is not None:
            first.setdefault(sample.start_ms // _STEP_MS, sample)
    end = max((s.end_ms for s in samples), default=0)
    flags: list[bool | None] = []
    for bucket in range(math.ceil(end / _STEP_MS)):
        a = first.get(bucket)
        b = first.get(bucket + _SPAN_MS // _STEP_MS)
        if a is None or b is None or b.start_ms <= a.start_ms:
            flags.append(None)
            continue
        assert a.latitude is not None and a.longitude is not None
        assert b.latitude is not None and b.longitude is not None
        seconds = (b.start_ms - a.start_ms) / 1000
        north = (b.latitude - a.latitude) * _EARTH_M_PER_DEG
        east = (
            (b.longitude - a.longitude)
            * _EARTH_M_PER_DEG
            * math.cos(math.radians(a.latitude))
        )
        horizontal = math.hypot(north, east) / seconds
        vertical = (
            abs(b.altitude - a.altitude) / seconds
            if a.altitude is not None and b.altitude is not None
            else 0.0
        )
        gimbal = 0.0
        if a.gimbal_pitch is not None and b.gimbal_pitch is not None:
            gimbal += abs(b.gimbal_pitch - a.gimbal_pitch) / seconds
            if (
                max(abs(a.gimbal_pitch), abs(b.gimbal_pitch)) < _NADIR_PITCH_DEG
                and a.gimbal_yaw is not None
                and b.gimbal_yaw is not None
            ):
                turn = (b.gimbal_yaw - a.gimbal_yaw + 180) % 360 - 180
                gimbal += abs(turn) / seconds
        flags.append(
            horizontal >= rule.horizontal_mps
            or vertical >= rule.vertical_mps
            or gimbal >= rule.gimbal_dps
        )
    return flags


def suggest_trim(
    samples: list[TelemetrySample], rule: TrimRule | None = None
) -> tuple[int, int] | None:
    """Kept ``(start_ms, end_ms)``, or ``None`` when no sustained motion exists."""
    rule = rule or TrimRule()
    flags = _motion(samples, rule)
    hold = max(1, rule.hold_ms // _STEP_MS)
    moving = [i for i in range(len(flags) - hold + 1) if all(flags[i : i + hold])]
    if not moving:
        return None
    end_ms = max(s.end_ms for s in samples)
    start = min(moving[0] * _STEP_MS + rule.lead_in_ms, end_ms)
    end = min((moving[-1] + hold) * _STEP_MS, end_ms)
    if end - start < rule.min_keep_ms:
        return None
    return start, end


def losslesscut_project(
    media_name: str, duration_ms: int, keep: tuple[int, int]
) -> str:
    """A LosslessCut v2 project: dropped head, kept middle, dropped tail."""
    start, end = keep
    segments = []
    if start > 0:
        segments.append({"start": 0, "end": start / 1000, "selected": False})
    segments.append({"start": start / 1000, "end": end / 1000, "selected": True})
    if end < duration_ms:
        segments.append(
            {"start": end / 1000, "end": duration_ms / 1000, "selected": False}
        )
    document = {
        "version": 2,
        "mediaFileName": media_name,
        "cutSegments": [{**segment, "name": ""} for segment in segments],
    }
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"
