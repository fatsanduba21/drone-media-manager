"""Grouping boundaries use independent sequence, time and GPS evidence."""

from datetime import UTC, datetime, timedelta

from drone_media_manager.grouping.service import (
    ClipSignal,
    sequence_number,
    suggest_ranges,
)
from drone_media_manager.grouping.telemetry import parse_srt


def test_parse_dji_srt_coordinates_and_time() -> None:
    srt = """1
00:00:00,000 --> 00:00:00,033
2026-09-01 10:00:00.000 [latitude: -3.8501] [longitude: -32.4201]

2
00:00:01,000 --> 00:00:01,033
2026-09-01 10:00:01.000 [latitude: -3.8502] [longitude: -32.4202]
"""
    track = parse_srt(srt)
    assert track.sample_count == 2
    assert track.start_lat == -3.8501
    assert track.end_lon == -32.4202
    assert (
        track.start_time is not None
        and track.start_time.isoformat() == "2026-09-01T10:00:00"
    )


def test_srt_grouping_uses_gps_time_and_sequence() -> None:
    start = datetime(2026, 9, 1, 10, tzinfo=UTC)
    clips = [
        ClipSignal("a", "DJI_0001.MP4", start, -3.85, -32.42),
        ClipSignal(
            "b", "DJI_0002.MP4", start + timedelta(minutes=2), -3.8501, -32.4201
        ),
        ClipSignal("c", "DJI_0003.MP4", start + timedelta(minutes=3), -3.9, -32.5),
        ClipSignal(
            "d", "DJI_0010.MP4", start + timedelta(minutes=4), -3.9001, -32.5001
        ),
        ClipSignal("e", "DJI_0011.MP4", start + timedelta(hours=2), -3.9002, -32.5002),
    ]
    ranges = suggest_ranges(clips)
    assert [[clip.asset_id for clip in group.clips] for group in ranges] == [
        ["a", "b"],
        ["c"],
        ["d"],
        ["e"],
    ]
    assert "gps_distance_m" in ranges[1].evidence
    assert "sequence_gap" in ranges[2].evidence
    assert "time_gap_s" in ranges[3].evidence


def test_without_srt_sequence_and_time_still_work() -> None:
    start = datetime(2026, 9, 1, 10, tzinfo=UTC)
    clips = [
        ClipSignal("a", "DJI_0001.MP4", None, None, None),
        ClipSignal("b", "DJI_0002.MP4", None, None, None),
        ClipSignal("c", "DJI_0007.MP4", None, None, None),
        ClipSignal("d", "DJI_0008.MP4", start, None, None),
        ClipSignal("e", "DJI_0009.MP4", start + timedelta(hours=1), None, None),
    ]
    assert [
        [clip.asset_id for clip in group.clips] for group in suggest_ranges(clips)
    ] == [["a", "b"], ["c", "d"], ["e"]]


def test_parse_srt_with_timestamp_and_coordinates_on_separate_lines() -> None:
    srt = """1
00:00:00,000 --> 00:00:00,033
2026-09-01 10:00:00.000
<font>[latitude: -3.85] [longitude: -32.42]</font>

2
00:00:01,000 --> 00:00:01,033
2026-09-01 10:00:01.000
<font>[latitude: -3.86] [longitude: -32.43]</font>
"""
    track = parse_srt(srt)
    assert track.sample_count == 2
    assert track.start_time is not None
    assert track.end_time is not None
    assert (track.end_time - track.start_time).total_seconds() == 1


def test_continuous_srt_tracks_compare_previous_end_to_next_start() -> None:
    start = datetime(2026, 9, 1, 10, tzinfo=UTC)
    clips = [
        ClipSignal(
            "a",
            "DJI_0001.MP4",
            start,
            -3.85,
            -32.42,
            end_at=start + timedelta(minutes=59),
            end_lat=-3.9,
            end_lon=-32.5,
        ),
        ClipSignal("b", "DJI_0002.MP4", start + timedelta(hours=1), -3.9001, -32.5001),
    ]
    assert len(suggest_ranges(clips)) == 1


def test_dji_sequence_takes_priority_over_date_suffix() -> None:
    assert sequence_number("DJI_0014_2026-09-01.MP4") == 14
