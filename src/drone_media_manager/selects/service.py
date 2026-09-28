"""Keep the best scored take among visually similar peers as a suggestion."""

from __future__ import annotations

from typing import Any

ALGORITHM_VERSION = "select-v1"


def recommended_assets(rows: list[dict[str, Any]]) -> set[str]:
    chosen: set[str] = set()
    for row in sorted(
        rows,
        key=lambda r: (
            r.get("editorial_score") is None,
            -(r.get("editorial_score") or 0),
            str(r["asset_id"]),
        ),
    ):
        if row.get("editorial_score") is None or any(
            peer["asset_id"] in chosen for peer in row.get("similar_takes", [])
        ):
            continue
        chosen.add(str(row["asset_id"]))
    return chosen
