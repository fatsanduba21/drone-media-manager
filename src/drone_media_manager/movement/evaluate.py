"""Evaluate a locally labelled dataset: python -m drone_media_manager.movement.evaluate labels.json."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import TypedDict

from drone_media_manager.grouping.telemetry import parse_samples
from drone_media_manager.movement.classifier import ALGORITHM_VERSION, classify


class ClassMetrics(TypedDict):
    precision: float | None
    recall: float | None
    support: int


class Metrics(TypedDict):
    count: int
    unknown_rate: float
    per_class: dict[str, ClassMetrics]


def metrics(pairs: list[tuple[str, str]]) -> Metrics:
    if not pairs:
        raise ValueError("A labelled dataset must contain at least one case")
    per_class: dict[str, ClassMetrics] = {}
    for value in sorted({v for pair in pairs for v in pair}):
        true_positive = sum(
            expected == predicted == value for expected, predicted in pairs
        )
        predicted_count = sum(predicted == value for _, predicted in pairs)
        support = sum(expected == value for expected, _ in pairs)
        per_class[value] = {
            "precision": true_positive / predicted_count if predicted_count else None,
            "recall": true_positive / support if support else None,
            "support": support,
        }
    return {
        "count": len(pairs),
        "unknown_rate": sum(p == "UNKNOWN" for _, p in pairs) / len(pairs),
        "per_class": per_class,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    args = parser.parse_args()
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    pairs = []
    results = []
    for item in dataset:
        samples = (
            parse_samples(
                (args.dataset.parent / item["srt"]).read_text(encoding="utf-8-sig")
            )
            if item.get("srt")
            else []
        )
        if "start_ms" in item:
            samples = [
                s for s in samples if item["start_ms"] <= s.start_ms < item["end_ms"]
            ]
        reference = item.get("anchor")
        result = classify(
            samples, anchor=(reference[0], reference[1]) if reference else None
        )
        pairs.append((item["expected"], result.value))
        results.append(
            {"asset": item["asset"], "expected": item["expected"], **result.data()}
        )
    print(
        json.dumps(
            {
                "algorithm_version": ALGORITHM_VERSION,
                **metrics(pairs),
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
