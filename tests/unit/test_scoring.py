"""Explainable scores degrade to missing values rather than invented quality."""

import pytest
from PIL import Image, ImageDraw

from drone_media_manager.grouping.telemetry import TelemetrySample
from drone_media_manager.scoring.service import (
    DEFAULT_PROFILES,
    compare_takes,
    image_metrics,
    motion_metrics,
    weighted_score,
)


def test_redundancy_requires_complete_matching_context_and_usable_images() -> None:
    context = {
        "trip_id": "trip",
        "location_group_id": "group",
        "movement": "ORBITA",
        "subject": "barco",
        "media_type": "VIDEO",
    }
    rows = [
        {"asset_id": "a", "context": context, "fingerprint": "0"},
        {"asset_id": "b", "context": context, "fingerprint": "1"},
    ]
    for key, value in (
        ("trip_id", "other"),
        ("location_group_id", "other"),
        ("movement", "PAN"),
        ("subject", "praia"),
        ("media_type", "PHOTO"),
        ("movement", "UNKNOWN"),
        ("subject", None),
    ):
        rows.append(
            {
                "asset_id": key + str(value),
                "context": {**context, key: value},
                "fingerprint": "0",
            }
        )
    rows.append({"asset_id": "no-image", "context": context, "fingerprint": None})
    compare_takes(rows)
    assert rows[0]["similar_takes"] == [{"asset_id": "b", "distance": 1}]
    assert rows[0]["uniqueness_score"] == 3.1
    assert all(
        row["similar_takes"] == [] and row["uniqueness_score"] is None
        for row in rows[2:]
    )


def test_partial_weights_zero_and_missing_scores() -> None:
    assert weighted_score({}, DEFAULT_PROFILES["instagram"]) == (None, 0)
    assert weighted_score({"technical": 0}, {"technical": 30, "motion": 70}) == (0, 0.3)
    assert weighted_score(
        {"technical": 80, "motion": 40}, {"technical": 25, "motion": 75}
    ) == (50, 1)
    assert weighted_score({"technical": 80}, {"technical": 0, "motion": 100}) == (
        None,
        0,
    )


def test_thumbnail_evidence_and_uniform_images() -> None:
    blank = Image.new("RGB", (128, 128), "black")
    score, evidence, fingerprint = image_metrics(blank)
    assert score == 0 and fingerprint is None
    assert evidence["clipped_fraction"] == 1
    textured = Image.new("RGB", (128, 128), "gray")
    draw = ImageDraw.Draw(textured)
    for x in range(0, 128, 8):
        draw.rectangle((x, 0, x + 3, 127), fill=(200, 200, 200))
    score, evidence, fingerprint = image_metrics(textured)
    assert score > 50 and fingerprint is not None
    assert evidence["scope"] == "single_thumbnail"


def test_motion_wraparound_missing_and_irregular_timing() -> None:
    smooth = [
        TelemetrySample(i * 1000, (i + 1) * 1000, yaw=yaw)
        for i, yaw in enumerate((178, 179, -180, -179))
    ]
    assert motion_metrics([])[0] is None
    assert motion_metrics(smooth)[0] == 100
    rough = [
        TelemetrySample(i * 1000, (i + 1) * 1000, yaw=yaw)
        for i, yaw in enumerate((0, 30, 0, 30))
    ]
    assert motion_metrics(rough)[0] < 50
    assert motion_metrics([smooth[0]] * 4)[0] is None
    sparse = [smooth[0], TelemetrySample(1000, 2000), smooth[2]]
    assert motion_metrics(sparse)[0] is None


@pytest.mark.parametrize(
    "weights",
    [{"technical": -1}, {"technical": float("nan")}, {"unknown": 1}, {"technical": 0}],
)
def test_invalid_weights_rejected(weights: dict[str, float]) -> None:
    from drone_media_manager.scoring.service import validate_weights

    with pytest.raises(ValueError):
        validate_weights(weights)
