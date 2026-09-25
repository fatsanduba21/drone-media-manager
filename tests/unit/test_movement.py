"""Synthetic trajectories exercise conservative movement rules, not real accuracy."""

import math

import pytest

from drone_media_manager.grouping.telemetry import TelemetrySample, parse_samples
from drone_media_manager.movement.classifier import classify, segment_track


def track(kind: str, count: int = 41) -> list[TelemetrySample]:
    result = []
    for i in range(count):
        angle = math.radians(i * (9 if kind == "orbit" else 4.5))
        x = 30 * math.cos(angle) if kind in {"orbit", "half"} else 0
        y = 30 * math.sin(angle) if kind in {"orbit", "half"} else 0
        if kind in {"away", "toward", "line"}:
            x = 20 + (i if kind != "toward" else count - i) * 2
        result.append(
            TelemetrySample(
                start_ms=i * 1000,
                end_ms=(i + 1) * 1000,
                latitude=y / 111195,
                longitude=x / 111195,
                altitude=10
                + (i if kind in {"rocket", "up"} else -i if kind == "down" else 0),
                yaw=(170 + i * 3 + 180) % 360 - 180 if kind == "pan" else 0,
                gimbal_pitch=-90 if kind == "rocket" else 0,
            )
        )
    return result


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("orbit", "ORBITA"),
        ("half", "MEIA_ORBITA"),
        ("pan", "PAN"),
        ("rocket", "FOGUETE"),
        ("up", "SUBIDA"),
        ("down", "DESCIDA"),
        ("still", "HOVER"),
        ("line", "UNKNOWN"),
    ],
)
def test_classifier(kind: str, expected: str) -> None:
    result = classify(track(kind))
    assert result.value == expected
    assert result.algorithm_version == "movement-v1"
    assert 0 <= result.confidence <= 1
    assert result.evidence


def test_reference_required_and_stationary_pan_is_not_orbit() -> None:
    assert classify(track("away")).value == "UNKNOWN"
    assert classify(track("away"), anchor=(0, 0)).value == "AFASTAMENTO"
    assert classify(track("toward"), anchor=(0, 0)).value == "APROXIMACAO"
    assert classify(track("pan")).value == "PAN"
    assert classify([]).value == "UNKNOWN"


def test_parser_keeps_timing_optional_motion_fields_and_rejects_invalid_samples() -> (
    None
):
    samples = parse_samples("""1
00:00:00,000 --> 00:00:01,000
[latitude: -3.8] [longitude: -32.4] [rel_alt: 30.2 abs_alt: 80]
[drone_yaw: 179] [gimbal_pitch: -90] [hs: 2.4] [heading: 21]

2
00:00:01,000 --> 00:00:02,000
[latitude: 999] [longitude: -32.4] [rel_alt: 31]

3
00:00:02,000 --> 00:00:03,000
[rel_alt: 32] [yaw: -179]
""")
    assert len(samples) == 3
    assert samples[0].altitude == 30.2
    assert samples[0].yaw == 179
    assert samples[0].gimbal_pitch == -90
    assert samples[0].speed == 2.4
    assert samples[0].heading == 21
    assert samples[1].latitude is None
    assert samples[2].longitude is None
    assert classify(samples).value == "UNKNOWN"


def test_segments_preserve_hover_then_pan_and_missing_telemetry() -> None:
    samples = track("still", 10)
    samples += [
        TelemetrySample(
            start_ms=(10 + i) * 1000,
            end_ms=(11 + i) * 1000,
            latitude=0,
            longitude=0,
            altitude=10,
            yaw=i * 8,
            gimbal_pitch=0,
        )
        for i in range(10)
    ]
    segments = segment_track(samples, duration_ms=20000)
    assert [s[2].value for s in segments] == ["HOVER", "PAN"]
    assert segments[0][0] == 0 and segments[-1][1] == 20000
    assert segment_track([], duration_ms=10000)[0][2].value == "UNKNOWN"


def test_bad_time_gps_jump_and_missing_yaw_are_unknown() -> None:
    samples = track("still", 10)
    samples[4] = TelemetrySample(4000, 5000, 30, 40, 10, 0)
    assert classify(samples).value == "UNKNOWN"
    assert classify(list(reversed(track("orbit")))).value == "UNKNOWN"
    assert (
        classify(
            [TelemetrySample(i * 1000, (i + 1) * 1000, 0, 0) for i in range(10)]
        ).value
        == "UNKNOWN"
    )


def test_rotation_out_and_back_does_not_become_hover() -> None:
    samples = [
        TelemetrySample(i * 1000, (i + 1) * 1000, 0, 0, 10, yaw, 0)
        for i, yaw in enumerate([0, 30, 60, 30, 0])
    ]
    assert classify(samples).value == "PAN"


def test_hover_then_orbit_has_separate_segments_with_evidence() -> None:
    from dataclasses import replace

    orbit = track("orbit", 41)
    hover = [
        replace(orbit[0], start_ms=i * 1000, end_ms=(i + 1) * 1000) for i in range(10)
    ]
    samples = hover + [
        replace(s, start_ms=s.start_ms + 10000, end_ms=s.end_ms + 10000) for s in orbit
    ]
    segments = segment_track(samples, duration_ms=51000)
    assert segments[0][2].value == "HOVER"
    assert any(s[2].value == "ORBITA" for s in segments)
    assert all(
        s[2].evidence.get("sample_count") is not None
        for s in segments
        if s[2].value != "UNKNOWN"
    )


def test_evaluation_reports_confusion_and_unknown_rate() -> None:
    from drone_media_manager.movement.evaluate import metrics

    report = metrics([("PAN", "PAN"), ("ORBITA", "UNKNOWN"), ("PAN", "ORBITA")])
    assert report["unknown_rate"] == pytest.approx(1 / 3)
    assert report["per_class"]["PAN"]["precision"] == 1
    assert report["per_class"]["PAN"]["recall"] == 0.5


@pytest.mark.parametrize("kind,expected", [("pan", "PAN"), ("rocket", "FOGUETE")])
def test_slow_movement_is_retained_by_segments(kind: str, expected: str) -> None:
    samples = [
        TelemetrySample(
            i * 1000,
            (i + 1) * 1000,
            0,
            0,
            10 + i * 0.75 if kind == "rocket" else 10,
            i * 3 if kind == "pan" else 0,
            -90,
        )
        for i in range(30)
    ]
    assert classify(samples).value == expected
    assert [s[2].value for s in segment_track(samples, duration_ms=30000)] == [expected]


def test_missing_leading_telemetry_does_not_extend_motion_to_unobserved_time() -> None:
    from dataclasses import replace

    samples = [
        replace(s, start_ms=s.start_ms + 10000, end_ms=s.end_ms + 10000)
        for s in track("pan", 10)
    ]
    assert segment_track(samples, duration_ms=20000)[0][2].value == "UNKNOWN"


@pytest.mark.parametrize(
    "yaw,pitch,expected",
    [(0, 0, "TRAVELLING"), (90, -90, "SOBREVOO"), (90, 0, "UNKNOWN")],
)
def test_direction_and_camera_support_horizontal_classes(
    yaw: float, pitch: float, expected: str
) -> None:
    from dataclasses import replace

    samples = [
        replace(s, heading=90, yaw=yaw, gimbal_pitch=pitch) for s in track("line")
    ]
    assert classify(samples).value == expected


def test_static_on_ground_and_unstable_radius() -> None:
    from dataclasses import replace

    assert (
        classify([replace(s, altitude=0) for s in track("still")]).value == "ESTATICO"
    )
    distorted = [
        replace(s, longitude=s.longitude * (1 if i % 2 else 2))
        for i, s in enumerate(track("orbit"))
    ]
    assert classify(distorted).value == "UNKNOWN"
