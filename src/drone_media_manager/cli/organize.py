"""Standalone Windows PLAN/APPLY entry point for editorial OMV output."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from drone_media_manager.organize import apply_plan, build_plan, probe_video
from drone_media_manager.progress import Progress, terminal_progress
from drone_media_manager.triage import apply_sort, plan_sort


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dmm-organize")
    parser.add_argument(
        "command",
        choices=("plan", "apply", "sort"),
        help="sort: move local originals into format folders (dry run without --apply)",
    )
    parser.add_argument("--source", required=True)
    parser.add_argument("--trip")
    parser.add_argument("--poi")
    parser.add_argument("--output-omv")
    parser.add_argument("--movement")
    parser.add_argument("--people")
    parser.add_argument("--date")
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--apply", action="store_true", help="sort: perform moves")
    return parser


def _sort(args: argparse.Namespace, progress: Progress) -> dict[str, Any]:
    folder = Path(args.source)
    if not folder.is_dir():
        raise ValueError(f"source is not a directory: {folder}")
    moves = plan_sort(
        folder,
        prober=lambda path: probe_video(path, args.ffprobe),
        progress=progress,
    )
    results = (
        apply_sort(moves, progress)
        if args.apply
        else [(move, move.status) for move in moves]
    )
    items = [
        {
            "file": move.source.name,
            "category": move.category,
            "folder": move.target.parent.name if move.target else None,
            "status": status,
            "srt": [sidecar.name for sidecar, _ in move.sidecars],
            "detail": move.detail,
        }
        for move, status in results
    ]
    counts: dict[str, int] = {}
    for move, _ in results:
        if move.category:
            counts[move.category] = counts.get(move.category, 0) + 1
    failed = [i for i in items if i["status"] not in {"MOVE", "MOVED"}]
    return {
        "status": "ERROR" if failed else ("SORTED" if args.apply else "PLANNED"),
        "apply": args.apply,
        "counts": counts,
        "items": items,
        "errors": [
            f"{i['file']}: {i['status']} {i['detail'] or ''}".strip() for i in failed
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command != "sort" and (not args.trip or not args.output_omv):
        parser.error("plan/apply require --trip and --output-omv")
    try:
        with terminal_progress() as progress:
            report = _run(args, progress)
    except (OSError, ValueError) as error:
        report = {"status": "ERROR", "errors": [str(error)]}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report.get("status") in {"ERROR", "CONFLICT"} or report.get("errors"):
        return 2
    return 0


def _run(args: argparse.Namespace, progress: Progress) -> dict[str, Any]:
    if args.command == "sort":
        return _sort(args, progress)
    plan = build_plan(
        args.source,
        args.output_omv,
        args.trip,
        args.poi,
        movement=args.movement,
        people=args.people,
        capture_date=args.date,
        ffprobe=args.ffprobe,
        progress=progress,
    )
    if args.command == "plan":
        return plan.preview(progress)
    return apply_plan(plan, progress)


if __name__ == "__main__":
    raise SystemExit(main())
