"""A rank only suggests; no score or context never silently selects media."""

from drone_media_manager.selects.service import recommended_assets


def test_recommend_one_per_similar_set_and_keep_unscored_manual() -> None:
    rows = [
        {
            "asset_id": "best",
            "editorial_score": 90,
            "similar_takes": [{"asset_id": "near", "distance": 2}],
        },
        {
            "asset_id": "near",
            "editorial_score": 80,
            "similar_takes": [{"asset_id": "best", "distance": 2}],
        },
        {"asset_id": "distinct", "editorial_score": 70, "similar_takes": []},
        {"asset_id": "unknown", "editorial_score": None, "similar_takes": []},
    ]
    assert recommended_assets(rows) == {"best", "distinct"}
