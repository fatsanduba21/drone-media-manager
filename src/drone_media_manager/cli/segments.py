"""LosslessCut helpers: trim suggestions and per-segment SRT sidecars."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from drone_media_manager.segments.sidecar import (
    plan_folder,
    plan_projects,
    probe_duration_ms,
    write_project,
    write_sidecar,
)


def _srt(args: argparse.Namespace) -> list[dict[str, Any]]:
    plans = plan_folder(
        args.folder, prober=None if args.no_probe else probe_duration_ms
    )
    return [
        {
            "segment": plan.segment.name,
            "sidecar": plan.sidecar.name,
            "status": write_sidecar(plan) if args.apply else plan.status,
            "source": plan.source,
            "start_ms": plan.start_ms,
            "end_ms": plan.end_ms,
            "samples": plan.sample_count,
        }
        for plan in plans
    ]


def _suggest(args: argparse.Namespace) -> list[dict[str, Any]]:
    return [
        {
            "original": plan.original.name,
            "project": str(plan.project),
            "status": write_project(plan) if args.apply else plan.status,
            "source": plan.source,
            "keep_start_ms": plan.keep_start_ms,
            "keep_end_ms": plan.keep_end_ms,
            "duration_ms": plan.duration_ms,
        }
        for plan in plan_projects(args.folder, args.output)
    ]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dmm-segments")
    parser.add_argument(
        "command",
        choices=("srt", "suggest"),
        help="srt: sidecars for cut segments; suggest: LosslessCut trim projects",
    )
    parser.add_argument("folder", type=Path, help="folder with segments or originals")
    parser.add_argument(
        "--apply", action="store_true", help="write files (default: dry run)"
    )
    parser.add_argument(
        "--no-probe",
        action="store_true",
        help="srt: trust filename times; skip ffprobe keyframe alignment",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="suggest: LosslessCut output folder, where it looks for -proj.llc",
    )
    args = parser.parse_args(argv)
    if not args.folder.is_dir() or (args.output and not args.output.is_dir()):
        print("folders must exist and be directories", file=sys.stderr)
        return 2
    report = _srt(args) if args.command == "srt" else _suggest(args)
    print(
        json.dumps(
            {"command": args.command, "apply": args.apply, "items": report},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 2 if any(item["status"] == "NO_TELEMETRY" for item in report) else 0


if __name__ == "__main__":
    raise SystemExit(main())
