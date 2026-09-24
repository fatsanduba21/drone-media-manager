"""Standalone Windows PLAN/APPLY entry point for editorial OMV output."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from drone_media_manager.organize import apply_plan, build_plan


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dmm-organize")
    parser.add_argument("command", choices=("plan", "apply"))
    parser.add_argument("--source", required=True)
    parser.add_argument("--trip", required=True)
    parser.add_argument("--poi")
    parser.add_argument("--output-omv", required=True)
    parser.add_argument("--movement")
    parser.add_argument("--people")
    parser.add_argument("--date")
    parser.add_argument("--ffprobe", default="ffprobe")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        plan = build_plan(
            args.source,
            args.output_omv,
            args.trip,
            args.poi,
            movement=args.movement,
            people=args.people,
            capture_date=args.date,
            ffprobe=args.ffprobe,
        )
        report = plan.preview() if args.command == "plan" else apply_plan(plan)
    except (OSError, ValueError) as error:
        report = {"status": "ERROR", "errors": [str(error)]}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report.get("status") in {"ERROR", "CONFLICT"} or report.get("errors"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
