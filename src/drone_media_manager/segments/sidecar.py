"""Recover per-segment SRT sidecars from the parent clip's telemetry.

LosslessCut names exports ``<stem>-HH.MM.SS.mmm-HH.MM.SS.mmm[-segN].<ext>`` and
drops the DJI data tracks. The parent's telemetry is still available from its
SRT, its MP4 ``djmd`` track or LosslessCut's ``<stem>-stream-N-data-djmd.bin``
dump. This module slices it to the segment and renders a DJI-style SRT that
the organizer pairs with the segment like any camera SRT. Media files are only
read; sidecars are created exclusively and never overwrite existing files.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from drone_media_manager.grouping.embedded import decode_track, read_embedded_samples
from drone_media_manager.grouping.telemetry import TelemetrySample, parse_samples

_SEGMENT = re.compile(
    r"^(?P<stem>.+?)-(?P<start>\d{2}\.\d{2}\.\d{2}\.\d{3})"
    r"-(?P<end>\d{2}\.\d{2}\.\d{2}\.\d{3})(?:-seg\d+)?\.mp4$",
    re.IGNORECASE,
)
_DJI_START = re.compile(r"^DJI_(\d{14})_")
_MAX_SRT_BYTES = 8 * 1024 * 1024
_KEYFRAME_TOLERANCE_MS = 5000

Prober = Callable[[Path], int | None]


@dataclass(frozen=True)
class SegmentName:
    stem: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class SidecarPlan:
    segment: Path
    sidecar: Path
    status: str
    source: str | None = None
    start_ms: int | None = None
    end_ms: int | None = None
    sample_count: int = 0
    content: str | None = None


def _clock_ms(value: str) -> int:
    hours, minutes, seconds, millis = (int(part) for part in value.split("."))
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + millis


def parse_segment_name(name: str) -> SegmentName | None:
    match = _SEGMENT.match(name)
    if match is None:
        return None
    start, end = _clock_ms(match["start"]), _clock_ms(match["end"])
    if end <= start:
        return None
    return SegmentName(match["stem"], start, end)


def probe_duration_ms(path: Path, *, runner: Any = subprocess.run) -> int | None:
    """Actual container duration; ``None`` when ffprobe is unavailable."""
    try:
        result = runner(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            check=True,
            timeout=120,
        )
        duration = float(json.loads(result.stdout)["format"]["duration"])
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
    ):
        return None
    return round(duration * 1000) if duration > 0 else None


def _candidates(folder: Path) -> list[Path]:
    return [folder, folder.parent] if folder.parent != folder else [folder]


def find_parent_telemetry(
    folder: Path, stem: str
) -> tuple[list[TelemetrySample], str | None]:
    """Parent SRT, then LosslessCut ``djmd`` dump, then the parent MP4 itself."""
    for directory in _candidates(folder):
        for suffix in (".SRT", ".srt"):
            srt = directory / f"{stem}{suffix}"
            if srt.is_file() and srt.stat().st_size <= _MAX_SRT_BYTES:
                samples = parse_samples(
                    srt.read_text(encoding="utf-8-sig", errors="replace")
                )
                if any(s.latitude is not None for s in samples):
                    return samples, srt.name
    for directory in _candidates(folder):
        for dump in sorted(
            directory.glob(f"{_glob_escape(stem)}-stream-*-data-djmd.bin")
        ):
            samples = decode_track(dump.read_bytes())
            if samples:
                return samples, dump.name
    for directory in _candidates(folder):
        for suffix in (".MP4", ".mp4"):
            original = directory / f"{stem}{suffix}"
            if original.is_file():
                samples = read_embedded_samples(original)
                if samples:
                    return samples, original.name
    return [], None


def _glob_escape(value: str) -> str:
    return re.sub(r"([\[\]*?])", r"[\1]", value)


def slice_samples(
    samples: list[TelemetrySample], start_ms: int, end_ms: int
) -> list[TelemetrySample]:
    """Samples overlapping ``[start_ms, end_ms)``, rebased to the segment start."""
    result = []
    for sample in samples:
        if sample.end_ms <= start_ms or sample.start_ms >= end_ms:
            continue
        begin = max(sample.start_ms, start_ms) - start_ms
        finish = min(sample.end_ms, end_ms) - start_ms
        if finish > begin:
            result.append(replace(sample, start_ms=begin, end_ms=finish))
    return result


def _timestamp(value: int) -> str:
    hours, rest = divmod(value, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    seconds, millis = divmod(rest, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"


def _number(value: float, digits: int) -> str:
    text = f"{value:.{digits}f}"
    return text[1:] if text.startswith("-") and float(text) == 0 else text


def render_srt(samples: list[TelemetrySample], clock: datetime | None) -> str:
    """DJI-style cues readable by ``parse_samples``/``parse_srt`` and editors."""
    blocks = []
    for index, sample in enumerate(samples, start=1):
        fields = []
        if sample.latitude is not None and sample.longitude is not None:
            fields.append(f"[latitude: {_number(sample.latitude, 6)}]")
            fields.append(f"[longitude: {_number(sample.longitude, 6)}]")
        if sample.altitude is not None:
            fields.append(f"[rel_alt: {_number(sample.altitude, 3)}]")
        gimbal = []
        if sample.gimbal_yaw is not None:
            gimbal.append(f"gb_yaw: {_number(sample.gimbal_yaw, 1)}")
        if sample.gimbal_pitch is not None:
            gimbal.append(f"gb_pitch: {_number(sample.gimbal_pitch, 1)}")
        if gimbal:
            fields.append(f"[{' '.join(gimbal)}]")
        lines = [
            str(index),
            f"{_timestamp(sample.start_ms)} --> {_timestamp(sample.end_ms)}",
            (
                f'<font size="28">FrameCnt: {index}, '
                f"DiffTime: {sample.end_ms - sample.start_ms}ms"
            ),
        ]
        if clock is not None:
            moment = clock + timedelta(milliseconds=sample.start_ms)
            lines.append(
                moment.strftime("%Y-%m-%d %H:%M:%S.")
                + f"{moment.microsecond // 1000:03}"
            )
        lines.append(" ".join(fields) + " </font>")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"


def _recording_start(stem: str) -> datetime | None:
    match = _DJI_START.match(stem)
    if match is None:
        return None
    try:
        # DJI names and SRT clocks are zone-less local wall time, as is parse_srt.
        return datetime.strptime(match[1], "%Y%m%d%H%M%S")  # noqa: DTZ007
    except ValueError:
        return None


def plan_folder(
    folder: Path, *, prober: Prober | None = probe_duration_ms
) -> list[SidecarPlan]:
    """Plan one sidecar per recognised segment; never writes."""
    plans = []
    cache: dict[str, tuple[list[TelemetrySample], str | None]] = {}
    for segment in sorted(folder.iterdir(), key=lambda p: p.name.casefold()):
        if not segment.is_file():
            continue
        name = parse_segment_name(segment.name)
        if name is None:
            continue
        sidecar = segment.with_suffix(".SRT")
        existing = [p for p in (sidecar, segment.with_suffix(".srt")) if p.exists()]
        if existing:
            plans.append(SidecarPlan(segment, existing[0], "EXISTS"))
            continue
        if name.stem not in cache:
            cache[name.stem] = find_parent_telemetry(folder, name.stem)
        samples, source = cache[name.stem]
        if not samples:
            plans.append(SidecarPlan(segment, sidecar, "NO_TELEMETRY"))
            continue
        start = name.start_ms
        actual = prober(segment) if prober is not None else None
        if (
            actual is not None
            and 0 <= name.end_ms - actual <= start
            and start - (name.end_ms - actual) <= _KEYFRAME_TOLERANCE_MS
        ):
            # Lossless cuts begin at the preceding keyframe.
            start = name.end_ms - actual
        sliced = slice_samples(samples, start, name.end_ms)
        if not any(s.latitude is not None for s in sliced):
            plans.append(SidecarPlan(segment, sidecar, "NO_TELEMETRY", source))
            continue
        recording = _recording_start(name.stem)
        clock = recording + timedelta(milliseconds=start) if recording else None
        plans.append(
            SidecarPlan(
                segment,
                sidecar,
                "CREATE",
                source,
                start,
                name.end_ms,
                len(sliced),
                render_srt(sliced, clock),
            )
        )
    return plans


def write_sidecar(plan: SidecarPlan) -> str:
    """Create the sidecar exclusively; an existing file is never replaced."""
    if plan.status != "CREATE" or plan.content is None:
        return plan.status
    try:
        with plan.sidecar.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(plan.content)
    except FileExistsError:
        return "EXISTS"
    return "CREATED"
