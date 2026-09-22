import json
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from drone_media_manager.organize import classify_video, probe_video


def test_classification_uses_display_dimensions() -> None:
    assert classify_video(3840, 2160, 0) == "YOUTUBE_16X9"
    assert classify_video(2160, 3840, 0) == "INSTAGRAM_9X16"
    assert classify_video(3840, 2160, 90) == "INSTAGRAM_9X16"
    assert classify_video(1920, 1440, 0) == "OUTROS_REVISAR"
    assert classify_video(1080, 1080, 0) == "OUTROS_REVISAR"
    assert classify_video(3840, 2160, 45) == "OUTROS_REVISAR"


def test_probe_reads_display_matrix_rotation_and_creation_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h265",
                "width": 3840,
                "height": 2160,
                "avg_frame_rate": "30000/1001",
                "side_data_list": [{"rotation": 90, "displaymatrix": "00000000: ..."}],
            }
        ],
        "format": {
            "duration": "10.5",
            "tags": {"creation_time": "2026-09-14T10:59:56Z"},
        },
    }

    def fake_run(*args: object, **kwargs: object) -> CompletedProcess[str]:
        return CompletedProcess(args, 0, json.dumps(payload), "")

    monkeypatch.setattr("drone_media_manager.organize.subprocess.run", fake_run)
    metadata = probe_video(Path("clip.mp4"))
    assert metadata["codec"] == "h265"
    assert metadata["duration_ms"] == 10500
    assert metadata["fps"] == 29.97003
    assert (metadata["display_width"], metadata["display_height"]) == (2160, 3840)
    assert metadata["display_matrix"] == "00000000: ..."
    assert metadata["creation_time"] == "2026-09-14T10:59:56Z"


def test_probe_uses_display_matrix_when_rotation_field_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    matrix = (
        "\n00000000:            0      -65536           0"
        "\n00000001:        65536           0           0"
        "\n00000002:            0           0  1073741824\n"
    )
    payload = {
        "streams": [
            {
                "codec_type": "video",
                "width": 3840,
                "height": 2160,
                "side_data_list": [{"displaymatrix": matrix}],
            }
        ],
        "format": {"duration": "1.0"},
    }

    def fake_run(*args: object, **kwargs: object) -> CompletedProcess[str]:
        return CompletedProcess(args, 0, json.dumps(payload), "")

    monkeypatch.setattr("drone_media_manager.organize.subprocess.run", fake_run)
    metadata = probe_video(Path("clip.mp4"))
    assert metadata["rotation_degrees"] == 90
    assert (metadata["display_width"], metadata["display_height"]) == (2160, 3840)
